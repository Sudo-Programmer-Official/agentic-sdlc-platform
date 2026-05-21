#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:8000/api/v1}"
PROJECT_ID="${1:-}"
OUT="${OUT:-/tmp/frontend_stability_benchmark.csv}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/benchmark_frontend_stability.sh <project_id>" >&2
  exit 1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1" >&2; exit 1; }
}
require_cmd curl
require_cmd jq

TASKS=(
  "Genesis foundation|Initialize app shell, design primitives, topology, and composition zones."
  "Add Hero Section|Add hero section in the hero zone only."
  "Add Testimonials Section|Add testimonials section in testimonials zone only."
  "Add Pricing Section|Add pricing section in pricing zone only."
  "Add CTA Section|Add CTA section in cta zone only."
  "Polish Landing Page|Polish landing page spacing, typography, responsiveness only."
  "Add Lead Capture Form|Add lead capture form section and wire submit behavior."
  "Add Analytics Tracking|Add analytics tracking for hero, CTA, and form events."
  "Add Dashboard Page|Add a dashboard page without modifying landing shell topology."
  "Preview + PR|Validate preview readiness and prepare PR-safe diff."
)

if [[ ! -f "$OUT" ]]; then
  echo "task_idx,task_title,task_id,run_id,run_status,shell_rewrite_detected,landing_rewrite_detected,finalized,timestamp_utc" > "$OUT"
fi

for i in "${!TASKS[@]}"; do
  IFS='|' read -r TITLE DESC <<< "${TASKS[$i]}"
  TASK_JSON=$(curl -sS -X POST "$API/store/projects/$PROJECT_ID/tasks" -H "Content-Type: application/json" -d "$(jq -nc --arg t "$TITLE" --arg d "$DESC" '{title:$t,description:$d}')")
  TASK_ID=$(echo "$TASK_JSON" | jq -r '.id')
  if [[ -z "$TASK_ID" || "$TASK_ID" == "null" ]]; then
    echo "Failed to create task for step $((i+1)): $TITLE" >&2
    exit 1
  fi

  RUN_JSON=$(curl -sS -X POST "$API/store/projects/$PROJECT_ID/runs" -H "Content-Type: application/json" -d "$(jq -nc --arg tid "$TASK_ID" '{executor:"codex",task_id:$tid}')")
  RUN_ID=$(echo "$RUN_JSON" | jq -r '.id')
  if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
    echo "Failed to launch run for task $TASK_ID" >&2
    exit 1
  fi

  STATUS="RUNNING"
  for _ in $(seq 1 180); do
    STATUS=$(curl -sS "$API/store/runs/$RUN_ID" | jq -r '.status')
    if [[ "$STATUS" == "COMPLETED" || "$STATUS" == "FAILED" || "$STATUS" == "CANCELED" ]]; then
      break
    fi
    sleep 5
  done

  EVENTS=$(curl -sS "$API/store/runs/$RUN_ID/events")
  SHELL_REWRITE=$(echo "$EVENTS" | jq '[.[] | select((.payload.message // .message // "") | tostring | test("Shell protection violation|App\\.vue|PageShell\\.vue"))] | length')
  LANDING_REWRITE=$(echo "$EVENTS" | jq '[.[] | select((.payload.message // .message // "") | tostring | test("replace_landing_page|Zone composition violation|LandingPage\\.vue must be patched"))] | length')
  FINALIZED=0
  if [[ "$STATUS" == "COMPLETED" || "$STATUS" == "FAILED" || "$STATUS" == "CANCELED" ]]; then
    FINALIZED=1
  fi

  echo "$((i+1)),$TITLE,$TASK_ID,$RUN_ID,$STATUS,$SHELL_REWRITE,$LANDING_REWRITE,$FINALIZED,$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT"
  echo "[$((i+1))/10] $TITLE -> run=$RUN_ID status=$STATUS shell_rewrite_hits=$SHELL_REWRITE landing_rewrite_hits=$LANDING_REWRITE"
done

echo "Benchmark complete. Results: $OUT"
