#!/usr/bin/env bash
set -uo pipefail

BASE="${BASE:-http://localhost:8000}"
FRONTEND="${FRONTEND:-http://localhost:5173}"
REPORT="${REPORT:-final_smoke_report.txt}"
FAILURES=0

pass() { printf "PASS  %s\n" "$1" | tee -a "$REPORT"; }
fail() { printf "FAIL  %s\n" "$1" | tee -a "$REPORT"; FAILURES=$((FAILURES+1)); }
info() { printf "INFO  %s\n" "$1" | tee -a "$REPORT"; }

: > "$REPORT"
info "Darial final smoke test: $(date)"

check_http() {
  local expected="$1"
  local label="$2"
  shift 2
  local actual
  actual="$(curl -sS -o /tmp/darial_smoke_body -w '%{http_code}' "$@" || true)"
  if [[ "$actual" == "$expected" ]]; then
    pass "$label -> HTTP $actual"
  else
    fail "$label -> expected $expected, got $actual"
    head -c 500 /tmp/darial_smoke_body | tee -a "$REPORT"
    printf "\n" | tee -a "$REPORT"
  fi
}

info "1. Docker containers"
if docker compose ps >> "$REPORT" 2>&1; then
  unhealthy="$(docker compose ps --format json 2>/dev/null | grep -E '"Health":"(unhealthy|starting)"' || true)"
  exited="$(docker compose ps --format json 2>/dev/null | grep -E '"State":"(exited|dead)"' || true)"
  if [[ -z "$unhealthy$exited" ]]; then
    pass "Compose services are running"
  else
    fail "Some compose services are not ready"
  fi
else
  fail "docker compose ps failed"
fi

info "2. Public endpoints"
check_http 200 "Frontend" "$FRONTEND"
check_http 200 "OpenAPI" "$BASE/openapi.json"

info "3. Backend Python compile"
if docker compose exec -T backend python -m compileall -q app >> "$REPORT" 2>&1; then
  pass "Backend compile"
else
  fail "Backend compile"
fi

info "4. Frontend build"
if docker compose exec -T frontend npm run build >> "$REPORT" 2>&1; then
  pass "Frontend build"
else
  fail "Frontend build"
fi

info "5. RBAC principals"
principals="$(curl -fsS "$BASE/api/rbac/principals" 2>>"$REPORT" || true)"
if [[ -n "$principals" ]]; then
  pass "Principal list"
else
  fail "Principal list"
fi

principal_id() {
  local email="$1"
  printf '%s' "$principals" | python3 -c \
    'import json,sys; email=sys.argv[1]; rows=json.load(sys.stdin); print(next((x["id"] for x in rows if x["email"]==email), ""))' \
    "$email" 2>/dev/null || true
}

ADMIN="$(principal_id admin@darial.local)"
AUDITOR="$(principal_id auditor@darial.local)"
FINOPS="$(principal_id finops@darial.local)"

if [[ -n "$ADMIN" && -n "$AUDITOR" && -n "$FINOPS" ]]; then
  pass "Admin, auditor and finops principals exist"
else
  fail "Required demo principals are missing"
fi

if [[ -n "$AUDITOR" ]]; then
  info "6. External Auditor API access"
  check_http 200 "Auditor reports" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/observability/reports/management"

  check_http 200 "Auditor violations" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/observability/violations"

  check_http 200 "Auditor policies" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/observability/policies"

  check_http 403 "Auditor economics denied" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/observability/dashboard/summary"

  check_http 403 "Auditor products denied" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/ai-products"

  check_http 403 "Auditor runs denied" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/observability/runs?limit=1"

  check_http 403 "Auditor RBAC denied" \
    -H "X-Darial-Principal: $AUDITOR" \
    "$BASE/api/rbac/summary"
fi

if [[ -n "$ADMIN" ]]; then
  info "7. Main admin endpoints"
  check_http 200 "Products" \
    -H "X-Darial-Principal: $ADMIN" \
    "$BASE/api/ai-products"

  check_http 200 "Runs" \
    -H "X-Darial-Principal: $ADMIN" \
    "$BASE/api/observability/runs?limit=3"

  check_http 200 "Economics" \
    -H "X-Darial-Principal: $ADMIN" \
    "$BASE/api/observability/dashboard/summary"

  check_http 200 "Management report" \
    -H "X-Darial-Principal: $ADMIN" \
    "$BASE/api/observability/reports/management"

  check_http 200 "RBAC summary" \
    -H "X-Darial-Principal: $ADMIN" \
    "$BASE/api/rbac/summary"
fi

info "8. Recent backend errors"
logs="$(docker compose logs --since=15m backend ingestion-worker synthetic-worker 2>&1 || true)"
critical="$(printf '%s' "$logs" | grep -Ei 'traceback|internal server error|exception' | grep -Ev 'HTTPException|CancelledError' || true)"
if [[ -z "$critical" ]]; then
  pass "No critical recent backend errors"
else
  fail "Critical errors found in recent logs"
  printf '%s\n' "$critical" | tail -30 | tee -a "$REPORT"
fi

info "9. Git safety"
if git status --short >> "$REPORT" 2>&1; then
  tracked_secrets="$(git ls-files 2>/dev/null | grep -E '(^|/)\.env$|\.pem$|\.key$' || true)"
  if [[ -z "$tracked_secrets" ]]; then
    pass "No obvious secret files tracked by Git"
  else
    fail "Potential secret files tracked by Git"
    printf '%s\n' "$tracked_secrets" | tee -a "$REPORT"
  fi
else
  info "Project is not a Git repository or status is unavailable"
fi

printf "\n" | tee -a "$REPORT"
if [[ "$FAILURES" -eq 0 ]]; then
  printf "FINAL RESULT: PASS\n" | tee -a "$REPORT"
  exit 0
else
  printf "FINAL RESULT: FAIL (%s checks)\n" "$FAILURES" | tee -a "$REPORT"
  exit 1
fi
