#!/usr/bin/env bash
# Run smoke_regression.sh across multiple repos/APIs and aggregate metrics with labels.
# Usage:
#   REPOS="small,http://localhost:8000/api/v1;legacy,http://localhost:9000/api/v1" OUT=./multi.csv ./scripts/eval_multi_repo.sh
# or pass a file: REPOS_FILE=repos.list ./scripts/eval_multi_repo.sh
# repos.list format: label,api_url (one per line)

set -euo pipefail

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}
require_cmd bash
require_cmd jq
require_cmd curl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMOKE="$SCRIPT_DIR/smoke_regression.sh"
OUT=${OUT:-/tmp/multi_repo_metrics.csv}

if [[ -n "${REPOS_FILE:-}" && -f "${REPOS_FILE:-}" ]]; then
  RAW_REPOS=$(cat "$REPOS_FILE" | tr '\n' ';')
else
  RAW_REPOS=${REPOS:-}
fi

if [[ -z "$RAW_REPOS" ]]; then
  echo "No repos specified. Set REPOS=\"label,api;label2,api2\" or REPOS_FILE." >&2
  exit 1
fi

IFS=';' read -ra REPO_ITEMS <<< "$RAW_REPOS"

if [[ ! -f "$OUT" ]]; then
  echo "label,$(head -n1 "$SMOKE" | grep -q '^timestamp' && head -n1 "$SMOKE")" >/dev/null 2>&1
fi

# Ensure output has header
if [[ ! -f "$OUT" ]]; then
  # Grab header from smoke_regression by running header branch
  TMP_OUT=$(mktemp)
  API="http://localhost:0" OUTFILE="$TMP_OUT" "$SMOKE" || true
  HEADER=$(head -n1 "$TMP_OUT" || echo "timestamp,run_id,status,failure_reason,run_completed,run_failed,workitem_dupes,lifecycle_events,input_tokens,output_tokens,total_tokens,avg_tokens_success,avg_fix_attempts,runs_failed_review,runs_failed_patch,time_to_green_started,started_at,finished_at")
  echo "label,$HEADER" >"$OUT"
  rm -f "$TMP_OUT"
fi

for item in "${REPO_ITEMS[@]}"; do
  label=$(echo "$item" | cut -d',' -f1)
  api=$(echo "$item" | cut -d',' -f2-)
  if [[ -z "$label" || -z "$api" ]]; then
    echo "Skipping malformed entry: $item" >&2
    continue
  fi
  echo "Running smoke for [$label] at [$api]"
  TMP=$(mktemp)
  API="$api" OUTFILE="$TMP" NAME="smoke-$label" "$SMOKE"
  tail -n1 "$TMP" | sed "s/^/$label,/" >>"$OUT"
  rm -f "$TMP"
done

echo "Multi-repo metrics appended to $OUT"
