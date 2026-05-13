#!/usr/bin/env bash
set -euo pipefail

API=${API:-http://localhost:8000/api/v1}

echo "Smoke: external mode"

# 0) ensure at least one active worker agent exists so scheduler can execute work
curl -s -X POST "$API/store/agents/register" \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke-worker","kind":"worker","executors":["dummy"],"max_concurrency":2,"capabilities":{"runtime-worker":true}}' \
  >/dev/null || true

# 1) create project
PID=$(curl -s -X POST "$API/store/projects" -H "Content-Type: application/json" -d '{"name":"smoke-proj","description":"smoke"}' | jq -r '.id')
echo "Project: $PID"

# 2) create document
DID=$(curl -s -X POST "$API/store/projects/$PID/documents" -H "Content-Type: application/json" -d '{"type":"prd","title":"smoke prd","body":"Smoke body"}' | jq -r '.id')
echo "Doc: $DID"

# 3) create tasks (minimal)
curl -s -X POST "$API/store/projects/$PID/tasks" -H "Content-Type: application/json" -d '{"title":"task 1","description":"demo"}' >/dev/null
curl -s -X POST "$API/store/projects/$PID/tasks" -H "Content-Type: application/json" -d '{"title":"task 2","description":"demo"}' >/dev/null

# 4) start run
RID=$(curl -s -X POST "$API/store/projects/$PID/runs" -H "Content-Type: application/json" -d '{"executor":"dummy"}' | jq -r '.id')
echo "Run: $RID"

# 5) wait for completion
for i in $(seq 1 120); do
  status=$(curl -s "$API/store/runs/$RID" | jq -r '.status')
  echo "Run status: $status"
  if [[ "$status" == "COMPLETED" || "$status" == "FAILED" ]]; then
    break
  fi
  sleep 1
done

# 6) assertions
EVENTS=$(curl -s "$API/store/runs/$RID/events")
RUN_COMPLETED=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="RUN_COMPLETED")] | length')
RUN_FAILED=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="RUN_FAILED")] | length')
WI_DUPES=$(echo "$EVENTS" | jq '
  [.[] | select(.event_type=="WORK_ITEM_DONE")
    | (.work_item_id // .payload.work_item_id // .task_id // .payload.task_id // empty)]
  | group_by(.)
  | map(select(length>1))
  | length
')
LIFECYCLE=$(echo "$EVENTS" | jq '[.[] | select(.event_type=="LIFECYCLE_SCORED")] | length')

echo "RUN_COMPLETED: $RUN_COMPLETED RUN_FAILED: $RUN_FAILED WI_DUPES: $WI_DUPES LIFECYCLE: $LIFECYCLE"

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

echo "Smoke external mode: PASS"
