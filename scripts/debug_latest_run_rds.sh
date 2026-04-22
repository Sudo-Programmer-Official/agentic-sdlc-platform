#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/apps/api/.env"

usage() {
  cat <<'USAGE'
Usage:
  scripts/debug_latest_run_rds.sh <project_id> [run_id]

Examples:
  scripts/debug_latest_run_rds.sh dde9d488-3942-4fe1-8af5-a36a70f95304
  scripts/debug_latest_run_rds.sh dde9d488-3942-4fe1-8af5-a36a70f95304 52f74e23-cf49-41a3-a6e6-1b23ec6b41a9
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

PROJECT_ID="${1:-}"
RUN_ID="${2:-}"

if [[ -z "${PROJECT_ID}" ]]; then
  usage
  exit 1
fi

if ! [[ "${PROJECT_ID}" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "project_id must be a UUID (received: ${PROJECT_ID})" >&2
  exit 1
fi

if [[ -n "${RUN_ID}" ]] && ! [[ "${RUN_ID}" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "run_id must be a UUID when provided (received: ${RUN_ID})" >&2
  exit 1
fi

resolve_database_url() {
  if [[ -n "${DATABASE_URL:-}" ]]; then
    printf '%s\n' "${DATABASE_URL}"
    return
  fi

  if [[ -f "${ENV_FILE}" ]]; then
    local from_env
    from_env="$(sed -n 's/^DATABASE_URL=//p' "${ENV_FILE}" | head -n 1 || true)"
    if [[ -n "${from_env}" ]]; then
      printf '%s\n' "${from_env}"
      return
    fi
  fi

  return 1
}

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but not found on PATH." >&2
  exit 1
fi

RAW_DB_URL="$(resolve_database_url || true)"
if [[ -z "${RAW_DB_URL}" ]]; then
  echo "Could not resolve DATABASE_URL from environment or ${ENV_FILE}" >&2
  exit 1
fi

# psql/libpq expects postgresql:// and sslmode=... query key.
DB_URL="$(printf '%s' "${RAW_DB_URL}" | sed 's/+asyncpg//; s/[?]ssl=/?sslmode=/')"

if [[ -z "${RUN_ID}" ]]; then
  RUN_ID="$(
    psql "${DB_URL}" -At -v ON_ERROR_STOP=1 \
      -c "select id from runs where project_id='${PROJECT_ID}' order by created_at desc limit 1;"
  )"
fi

if [[ -z "${RUN_ID}" ]]; then
  echo "No runs found for project ${PROJECT_ID}" >&2
  exit 1
fi

echo "Project: ${PROJECT_ID}"
echo "Run: ${RUN_ID}"
echo

psql "${DB_URL}" -v ON_ERROR_STOP=1 <<SQL
\pset pager off
\echo '== run summary =='
select
  id,
  status,
  executor,
  workspace_status,
  started_at,
  finished_at,
  created_at,
  updated_at
from runs
where id = '${RUN_ID}';

\echo ''
\echo '== work items =='
select
  id,
  key,
  type,
  status,
  attempt,
  max_attempts,
  started_at,
  finished_at,
  left(coalesce(last_error,''), 220) as last_error
from work_items
where run_id = '${RUN_ID}'
order by created_at asc;

\echo ''
\echo '== failed work item payload/result =='
select
  id,
  key,
  type,
  status,
  left(coalesce(payload::text,''), 900) as payload,
  left(coalesce(result::text,''), 900) as result
from work_items
where run_id = '${RUN_ID}'
  and status in ('FAILED', 'CANCELED')
order by created_at asc;

\echo ''
\echo '== ai job runs (latest first) =='
select
  id,
  work_item_id,
  workflow_type,
  status,
  error_kind,
  stop_reason,
  retry_count,
  selected_model_tier,
  left(coalesce(details_json::text,''), 500) as details
from ai_job_runs
where run_id = '${RUN_ID}'
order by created_at desc
limit 20;

\echo ''
\echo '== run events (chronological) =='
select
  event_type,
  ts,
  coalesce(message,'') as message,
  left(coalesce(payload::text,''), 280) as payload
from run_events
where run_id = '${RUN_ID}'
order by ts asc;

\echo ''
\echo '== artifacts =='
select
  id,
  type,
  uri,
  left(coalesce(extra_metadata::text,''), 240) as extra_metadata
from artifacts
where run_id = '${RUN_ID}'
order by created_at asc;

\echo ''
\echo '== run checkpoints =='
select
  id,
  checkpoint_id,
  kind,
  work_item_type,
  work_item_status,
  dirty_file_count,
  patch_bytes,
  created_at
from run_checkpoints
where run_id = '${RUN_ID}'
order by created_at asc;
SQL
