from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app"

patterns = {
    "organization_id": re.compile(r"\borganization_id\b"),
    "tenant_id": re.compile(r"\btenant_id\b"),
    "product_scope": re.compile(r"\bget_request_product_scope\b"),
    "ensure_product_access": re.compile(r"\bensure_product_access\b"),
}

results = {key: [] for key in patterns}

for path in BACKEND.rglob("*.py"):
    text = path.read_text(errors="ignore")

    for key, pattern in patterns.items():
        if pattern.search(text):
            results[key].append(str(path.relative_to(ROOT)))

print("=== Darial multi-tenancy audit ===")

for key, files in results.items():
    print(f"\n{key}: {len(files)} files")
    for filename in files[:20]:
        print("  -", filename)

has_real_tenant = bool(
    results["organization_id"] or results["tenant_id"]
)

if not has_real_tenant:
    print(
        "\nSTATUS: GAP\n"
        "В коде не найден organization_id/tenant_id. "
        "Текущий organization-wide RBAC является областью доступа, "
        "но не полноценной tenant isolation."
    )
    print(
        "\nRECOMMENDATION:\n"
        "Добавить Organization и organization_id в Product, Agent, "
        "Deployment, IngestionSource, AgentRun, Budget, Policy и Report; "
        "затем внедрить tenant filtering и negative isolation tests."
    )
else:
    print(
        "\nSTATUS: PARTIAL\n"
        "Tenant identifiers найдены. Требуется ручная проверка, "
        "что все query API фильтруют данные по tenant context."
    )
