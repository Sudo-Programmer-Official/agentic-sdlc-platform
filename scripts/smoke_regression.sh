#!/usr/bin/env bash
# Regression smoke that runs an external-mode loop, validates invariants, then records key metrics to CSV.
set -euo pipefail

API=${API:-http://localhost:8000/api/v1}
OUTFILE=${OUTFILE:-/tmp/smoke_regression_metrics.csv}
NAME=${NAME:-smoke-proj}

echo "Regression smoke (external mode) against $API"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}
require_cmd curl
require_cmd jq

ts_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# 1) create project
PID=$(curl -s -X POST "$API/store/projects" -H "Content-Type: application/json" -d "{\"name\":\"$NAME\",\"description\":\"smoke\"}" | jq -r '.id')
echo "Project: $PID"

# 2) create document
DID=$(curl -s -X POST "$API/store/projects/$PID/documents" -H "Content-Type: application/json" -d '{"type":"prd","title":"smoke prd","body":"Smoke body"}' | jq -r '.id')
echo "Doc: $DID"

# 3) create tasks (minimal)
curl -s -X POST "$API/store/projects/$PID/tasks" -H "Content-Type: application/json" -d '{"title":"task 1","description":"demo"}' >/dev/null
curl -s -X POST "$API/store/projects/$PID/tasks" -H "Content-Type: application/json" -d '{"title":"task 2","description":"demo"}' >/dev/null

# 4) start run (dummy executor keeps it fast)
RID=$(curl -s -X POST "$API/store/projects/$PID/runs" -H "Content-Type: application/json" -d '{"executor":"dummy"}' | jq -r '.id')
echo "Run: $RID"

started=$(ts_now)

# 5) wait for completion
for i in $(seq 1 60); do
  status=$(curl -s "$API/store/runs/$RID" | jq -r '.status')
  echo "Run status: $status"
  if [[ "$status" == "COMPLETED" || "$status" == "FAILED" ]]; then
    break
  fi
  sleep 1
done

# 6) invariants
EVENTS=$(curl -s "$API/store/runs/$RID/events")
RUN_COMPLETED=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="RUN_COMPLETED")] | length')
RUN_FAILED=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="RUN_FAILED")] | length')
FAIL_REASON=$(echo "$EVENTS" | jq -r '[.[] | select(.event_type=="RUN_FAILED")][-1].payload.reason // ""')
WI_DUPES=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="WORK_ITEM_DONE")] | group_by(.task_id) | map(select(length>1)) | length')
LIFECYCLE=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="LIFECYCLE_SCORED")] | length')

if [[ "$WI_DUPES" != "0" ]]; then
  echo "Fail: duplicate work item completions detected" >&2
  exit 1
fi

if [[ "$LIFECYCLE" == "0" ]]; then
  echo "Fail: no lifecycle scored event" >&2
  exit 1
fi

if [[ "$RUN_COMPLETED" == "0" && "$RUN_FAILED" == "0" ]]; then
  echo "Fail: run did not finalize" >&2
  exit 1
fi

finished=$(ts_now)

# 7) fetch metrics snapshot
METRICS=$(curl -s "$API/health/metrics")

# 8) extract key fields
input_tokens=$(echo "$METRICS" | jq -r '.usage.input_tokens // 0')
output_tokens=$(echo "$METRICS" | jq -r '.usage.output_tokens // 0')
total_tokens=$(echo "$METRICS" | jq -r '.usage.total_tokens // 0')
avg_tokens_success=$(echo "$METRICS" | jq -r '.usage.avg_tokens_per_successful_run // 0')
avg_fix_attempts=$(echo "$METRICS" | jq -r '.telemetry.avg_fix_attempts_per_run // 0')
runs_failed_review=$(echo "$METRICS" | jq -r '.telemetry.runs_failed_due_to_review // 0')
runs_failed_patch=$(echo "$METRICS" | jq -r '.telemetry.runs_failed_due_to_patch_guard // 0')
time_to_green=$(echo "$METRICS" | jq -r '.telemetry.time_to_green_avg_seconds // 0')
run_status=$(curl -s "$API/store/runs/$RID" | jq -r '.status')

# 9) write CSV (append header if new)
if [[ ! -f "$OUTFILE" ]]; then
  echo "timestamp,run_id,status,failure_reason,run_completed,run_failed,workitem_dupes,lifecycle_events,input_tokens,output_tokens,total_tokens,avg_tokens_success,avg_fix_attempts,runs_failed_review,runs_failed_patch,time_to_green_started,started_at,finished_at" >> "$OUTFILE"
fi
echo "$(ts_now),$RID,$run_status,\"$FAIL_REASON\",$RUN_COMPLETED,$RUN_FAILED,$WI_DUPES,$LIFECYCLE,$input_tokens,$output_tokens,$total_tokens,$avg_tokens_success,$avg_fix_attempts,$runs_failed_review,$runs_failed_patch,$time_to_green,$started,$finished" >> "$OUTFILE"

echo "Regression smoke: PASS (metrics appended to $OUTFILE)"
