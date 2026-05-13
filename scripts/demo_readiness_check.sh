#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${API_URL:-http://localhost:8000/api/v1}"
API_HEALTH_URL="${API_HEALTH_URL:-http://localhost:8000/api/v1/health/detail}"
API_DIR="$ROOT_DIR/apps/api"

ts_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[demo-readiness] Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq

if [[ ! -x "$API_DIR/.venv/bin/pytest" ]]; then
  echo "[demo-readiness] Missing pytest at $API_DIR/.venv/bin/pytest" >&2
  exit 1
fi

run_step() {
  local label="$1"
  shift
  echo
  echo "[$(ts_now)] STEP: $label"
  if "$@"; then
    echo "[$(ts_now)] PASS: $label"
  else
    echo "[$(ts_now)] FAIL: $label" >&2
    return 1
  fi
}

echo "==================================================="
echo "Demo Readiness Check"
echo "Start: $(ts_now)"
echo "API:   $API_URL"
echo "==================================================="

run_step "API health endpoint reachable" \
  sh -c "curl -fsS '$API_HEALTH_URL' | jq -e '.status == \"ok\" or .status == \"degraded\"' >/dev/null"

run_step "External-mode smoke" \
  sh -c "cd '$ROOT_DIR' && API='$API_URL' bash scripts/smoke_external_mode.sh"

run_step "Regression smoke + metrics" \
  sh -c "cd '$ROOT_DIR' && API='$API_URL' bash scripts/smoke_regression.sh"

run_step "Mission Control + Preview + Project API suite" \
  sh -c "cd '$API_DIR' && ./.venv/bin/pytest -q tests/test_run_launch.py tests/test_mission_control_overview_api.py tests/test_preview_api.py tests/test_project_summary.py tests/test_public_project_routes.py"

echo
echo "==================================================="
echo "Demo readiness: PASS"
echo "Finished: $(ts_now)"
echo "==================================================="
