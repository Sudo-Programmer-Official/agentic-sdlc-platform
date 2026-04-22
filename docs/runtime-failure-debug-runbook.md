# Runtime Failure Debug Runbook (RDS + Mission Control)

This runbook is for debugging a failed run quickly using the live AWS RDS Postgres state that backs Mission Control.

## Scope

Use this when:
- Mission Control shows `FAILED`, `BLOCKED`, or repeated recovery loops.
- You need to confirm the real blocker from database truth (not only UI summaries).
- You need to diagnose `WRITE_TESTS`, `RUN_TESTS`, `FIX_TEST_FAILURE`, patch guard, or context-limit failures.

## Inputs

- `project_id` (from Mission Control header)
- `run_id` (optional; if not provided, latest run for project is used)

## One-command debug path

Use the helper script:

```bash
scripts/debug_latest_run_rds.sh <project_id> [run_id]
```

Example:

```bash
scripts/debug_latest_run_rds.sh dde9d488-3942-4fe1-8af5-a36a70f95304
```

What it prints:
- run summary (`runs`)
- full work-item state (`work_items`)
- failed/canceled payload + result snippets
- AI routing/job stop reasons (`ai_job_runs`)
- event timeline (`run_events`)
- generated artifacts (`artifacts`)
- checkpoints (`run_checkpoints`)

## Manual SQL flow (if script is unavailable)

`DATABASE_URL` lives in `apps/api/.env` in local dev. Convert:
- `postgresql+asyncpg://...` -> `postgresql://...`
- `?ssl=require` -> `?sslmode=require`

### 1) Confirm latest run

```sql
select id, status, started_at, finished_at, created_at, updated_at
from runs
where project_id = '<project_id>'
order by created_at desc
limit 5;
```

### 2) Identify first failing work item

```sql
select id, key, type, status, attempt, max_attempts, started_at, finished_at, left(coalesce(last_error,''), 220) as last_error
from work_items
where run_id = '<run_id>'
order by created_at asc;
```

### 3) Inspect failed payload/result

```sql
select id, key, type, status, left(coalesce(payload::text,''), 1200) as payload, left(coalesce(result::text,''), 1200) as result
from work_items
where run_id = '<run_id>' and status in ('FAILED', 'CANCELED')
order by created_at asc;
```

### 4) Inspect AI stop reason and error kind

```sql
select id, work_item_id, workflow_type, status, error_kind, stop_reason, retry_count, selected_model_tier,
       left(coalesce(details_json::text,''), 800) as details
from ai_job_runs
where run_id = '<run_id>'
order by created_at desc
limit 20;
```

### 5) Reconstruct timeline and cancellation chain

```sql
select event_type, ts, coalesce(message,'') as message, left(coalesce(payload::text,''), 280) as payload
from run_events
where run_id = '<run_id>'
order by ts asc;
```

### 6) Pull generated diffs and test logs

```sql
select id, type, uri, left(coalesce(extra_metadata::text,''), 300) as extra_metadata
from artifacts
where run_id = '<run_id>'
order by created_at asc;
```

## Fast triage decision map

### A) `RUN_TESTS` failed and downstream items are blocked

Check:
- `work_items.result` for `RUN_TESTS` (pytest stack trace)
- then `WORK_ITEM_RECOVERY` event in `run_events`

If recovery item (`FIX_TEST_FAILURE`) also fails:
- inspect `ai_job_runs.stop_reason`, `error_kind`, and `details_json`

### B) `patch_guard_violation`

Typical signals:
- `ai_job_runs.error_kind = 'patch_guard_violation'`
- failed work item `result` contains touched-files mismatch

Action:
- compare `payload.expected_files` / scoped plan vs touched patch files in `artifacts.extra_metadata.content`.

### C) `context_limit_exceeded`

Typical signals:
- `ai_job_runs.stop_reason = 'context_limit_exceeded'`
- recovery step fails fast

Action:
- narrow failed-step context and avoid stuffing full logs into repair prompts.
- verify context filters in `details_json.filters_used`.

### D) Patch apply problems (`git apply --recount --check`)

Typical signals:
- command output includes `corrupt patch` or `patch does not apply`
- seen in run console command logs and failure artifacts

Action:
- inspect `git_diff` artifact content and target file drift.
- validate generated patch hunks against current workspace file content.

## Known recent failure pattern (example)

Observed in project `dde9d488-3942-4fe1-8af5-a36a70f95304`:
1. `RUN_TESTS` failed with `SyntaxError` in generated `test_index_html.py`.
2. Recovery `FIX_TEST_FAILURE` then failed with `context_limit_exceeded`.
3. Remaining review/integration/test nodes were canceled as blocked by terminal failure.

This is why Mission Control can show several `Blocked` items even when implementation steps are `DONE`.

## Operational notes

- Never paste full connection strings or credentials in tickets.
- Prefer sharing `run_id`, `project_id`, event sequence, and AI stop reason.
- For repeated failures, compare with previous completed run for the same project before changing policies.
