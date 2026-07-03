#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$HOME/Projects/Darial}"
cd "$PROJECT_DIR"

echo "=== SDK unit tests ==="
PYTHONPATH=sdk python3 -m unittest discover \
  -s sdk/tests \
  -p "test_*.py" \
  -v

echo
echo "=== Multi-tenancy audit ==="
python3 mvp_readiness/tenant_audit.py

echo
echo "=== Integration tests ==="
echo "Для полного запуска нужны переменные:"
echo "DARIAL_ADMIN_PRINCIPAL"
echo "DARIAL_TEST_PRODUCT_A"
echo "DARIAL_TEST_PRODUCT_B"
echo
python3 -m unittest \
  mvp_readiness.test_ingestion_integration \
  -v

echo
echo "RESULT: PASS"
