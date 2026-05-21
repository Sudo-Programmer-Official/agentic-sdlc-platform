#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:8000/api/v1}"
PROJECT_ID="${1:-}"
OUT="${OUT:-/tmp/frontend_convergence_benchmark.csv}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/benchmark_frontend_convergence.sh <project_id>" >&2
  exit 1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1" >&2; exit 1; }
}

require_cmd curl
require_cmd jq

if [[ ! -f "$OUT" ]]; then
  echo "task_idx,task_title,run_id,run_status,preview_ready,foundation_failed,topology_drift,shell_rewrite,import_repairs,timestamp_utc" > "$OUT"
fi

TASKS=(
  "Bootstrap foundation|Bootstrap the frontend foundation and validate topology."
  "Validate preview|Validate preview bootability for the foundation template."
  "Replace testimonials|Replace testimonials placeholder with concrete content inside zones only."
)

for i in "${!TASKS[@]}"; do
  IFS='|' read -r TITLE DESC <<< "${TASKS[$i]}"
  TASK_JSON=$(curl -sS -X POST "$API/store/projects/$PROJECT_ID/tasks" -H "Content-Type: application/json" -d "$(jq -nc --arg t "$TITLE" --arg d "$DESC" '{title:$t,description:$d}')")
  TASK_ID=$(echo "$TASK_JSON" | jq -r '.id')
  RUN_JSON=$(curl -sS -X POST "$API/store/projects/$PROJECT_ID/runs" -H "Content-Type: application/json" -d "$(jq -nc --arg tid "$TASK_ID" '{executor:"codex","task_id":$tid}')")
  RUN_ID=$(echo "$RUN_JSON" | jq -r '.id')
  STATUS="RUNNING"
  for _ in $(seq 1 180); do
    STATUS=$(curl -sS "$API/store/runs/$RUN_ID" | jq -r '.status')
    if [[ "$STATUS" == "COMPLETED" || "$STATUS" == "FAILED" || "$STATUS" == "CANCELED" ]]; then
      break
    fi
    sleep 2
  done
  EVENTS=$(curl -sS "$API/store/runs/$RUN_ID/events")
  PREVIEW_READY=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="PREVIEW_READY")] | length')
  FOUNDATION_FAILED=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="WORK_ITEM_FAILED" and ((.payload.message // .message // "") | tostring | test("Foundation prerequisite validation failed")))] | length')
  TOPOLOGY_DRIFT=$(echo "$EVENTS" | jq '[.[] | select((.payload.message // .message // "") | tostring | test("topology drift|shell rewrite|zone replacement"))] | length')
  SHELL_REWRITE=$(echo "$EVENTS" | jq '[.[] | select((.payload.message // .message // "") | tostring | test("PageShell|App\\.vue"))] | length')
  IMPORT_REPAIRS=$(echo "$EVENTS" | jq '[.[] | select((.payload.message // .message // "") | tostring | test("import.*repair|component-manifest"))] | length')
  echo "$((i+1)),$TITLE,$RUN_ID,$STATUS,$PREVIEW_READY,$FOUNDATION_FAILED,$TOPOLOGY_DRIFT,$SHELL_REWRITE,$IMPORT_REPAIRS,$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT"
  echo "[$((i+1))/3] $TITLE -> run=$RUN_ID status=$STATUS preview=$PREVIEW_READY drift=$TOPOLOGY_DRIFT"
done

echo "Benchmark complete. Results: $OUT"
