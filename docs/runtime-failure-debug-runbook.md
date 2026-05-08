# Runtime Failure Debug Runbook (RDS + Mission Control)

This runbook is for debugging a failed run quickly using the live AWS RDS Postgres state that backs Mission Control.

## Scope

Use this when:
- Mission Control shows `FAILED`, `BLOCKED`, or repeated recovery loops.
- You need to confirm the real blocker from database truth (not only UI summaries).
- You need to diagnose `WRITE_TESTS`, `RUN_TESTS`, `FIX_TEST_FAILURE`, patch guard, context-limit failures, or repository clone/auth failures.

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
- project contract summary + enforcement snapshot (`project_contracts`)
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

### 2) Confirm project contract enforcement state

```sql
select id, status, source, version, summary, derived_json->'enforcement' as enforcement
from project_contracts
where project_id = '<project_id>';
```

If `enforcement.enabled = true`, check whether failures are due to contract rules
(`disallow_inline_styles`, `enforce_color_tokens`, blocked patterns).

### 3) Identify first failing work item

```sql
select id, key, type, status, attempt, max_attempts, started_at, finished_at, left(coalesce(last_error,''), 220) as last_error
from work_items
where run_id = '<run_id>'
order by created_at asc;
```

### 4) Inspect failed payload/result

```sql
select id, key, type, status, left(coalesce(payload::text,''), 1200) as payload, left(coalesce(result::text,''), 1200) as result
from work_items
where run_id = '<run_id>' and status in ('FAILED', 'CANCELED')
order by created_at asc;
```

### 5) Inspect AI stop reason and error kind

```sql
select id, work_item_id, workflow_type, status, error_kind, stop_reason, retry_count, selected_model_tier,
       left(coalesce(details_json::text,''), 800) as details
from ai_job_runs
where run_id = '<run_id>'
order by created_at desc
limit 20;
```

### 6) Reconstruct timeline and cancellation chain

```sql
select event_type, ts, coalesce(message,'') as message, left(coalesce(payload::text,''), 280) as payload
from run_events
where run_id = '<run_id>'
order by ts asc;
```

### 7) Pull generated diffs and test logs

```sql
select id, type, uri, left(coalesce(extra_metadata::text,''), 300) as extra_metadata
from artifacts
where run_id = '<run_id>'
order by created_at asc;
```

### 8) Confirm repository auth strategy and stale workers

For repo-backed failures, always check the saved repo strategy and active workers before debugging SSH/GitHub credentials:

```sql
select id, provider, repo_url, repo_full_name, default_branch, installation_id, auth_strategy, updated_at
from project_repositories
where project_id = '<project_id>';
```

```sql
select id, name, status, last_heartbeat_at, executors, capabilities
from agents
where kind = 'worker'
order by last_heartbeat_at desc
limit 20;
```

Expected local state after a clean restart:

- one recent `ACTIVE` worker with executors such as `["dummy","codex","test"]`
- older local workers are `INACTIVE` with empty executors/capabilities
- public repos should have `auth_strategy = 'public_https'`
- private GitHub App repos should have `auth_strategy = 'github_app'`
- SSH repos should have `auth_strategy = 'ssh'`

If multiple old workers remain `ACTIVE`, they can still claim new work items and run stale code/config.

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
- if project contract enforcement is enabled, confirm whether violation came from:
  - inline style attributes in frontend files
  - non-token hex colors
  - blocked patterns from `project_contracts.derived_json.enforcement`

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

### E) Repo clone/auth failure: `auth_mode=ssh` when repo is public HTTPS

Typical failure:

```text
Host key verification failed.
fatal: Could not read from remote repository.
[auth_mode=ssh selection_reason=explicit_ssh_mode installation_id=... token_generated=False]
```

Do not assume this means the saved repo is still SSH. Confirm in order:

1. Project repository row:

   ```sql
   select repo_url, repo_full_name, default_branch, installation_id, auth_strategy
   from project_repositories
   where project_id = '<project_id>';
   ```

2. Runtime health:

   ```bash
   curl -sS http://127.0.0.1:8000/api/v1/health/detail
   ```

3. Live clone preflight:

   ```bash
   curl -sS -X POST \
     http://127.0.0.1:8000/api/v1/projects/<project_id>/repo/preflight \
     -H 'Content-Type: application/json' \
     -d '{"clone":true}'
   ```

   Healthy public HTTPS output includes:

   ```json
   {
     "ok": true,
     "auth_strategy": "public_https",
     "auth_mode": "plain",
     "credential_strategy": "anonymous_https"
   }
   ```

4. Worker agents:

   ```sql
   select id, name, status, last_heartbeat_at, executors
   from agents
   where kind = 'worker'
   order by last_heartbeat_at desc
   limit 20;
   ```

If the repo row is `public_https` and preflight passes, but a run still fails with `auth_mode=ssh`, the most likely cause is a stale active worker agent claiming work from RDS.

Immediate local recovery:

```bash
cd apps/api
.venv/bin/python -c "exec('''import asyncio
from sqlalchemy import update
from app.db.session import SessionLocal
from app.db.models import Agent
async def main():
    async with SessionLocal() as s:
        await s.execute(update(Agent).where(Agent.kind == 'worker', Agent.status == 'ACTIVE').values(status='INACTIVE', executors=[], capabilities=[]))
        await s.commit()
asyncio.run(main())
''')"
```

Then restart the full local stack, not only the API:

```bash
bash scripts/dev_stack.sh
```

Do not continue the already-failed run after this recovery. Fork or create a new run so the clean worker claims fresh work.

### F) Recovery was queued but immediately failed with `run_budget_exhausted`

Typical signals:

- `RUN_TESTS` failed first.
- `WORK_ITEM_RECOVERY` event says `Auto recovery queued FIX_TEST_FAILURE for failed RUN_TESTS.`
- `FIX_TEST_FAILURE_*` then fails with:
  - `error_kind = run_budget_exhausted`
  - `stop_reason = run_budget_exhausted`
  - `completion_token_cap = 0`
  - `budget_mode = BLOCKED`
- Mission Control shows `Run Cost Budget Exhausted`.

This means the recovery system did activate, but the execution contract blocked more autonomous model work.

Design reference: [Recovery Tiered Model Routing](architecture/recovery-tiered-model-routing.md).

Confirm with:

```sql
select id, work_item_id, workflow_type, status, error_kind, stop_reason, selected_model_tier,
       details->'metadata' as metadata
from ai_job_runs
where run_id = '<run_id>'
order by created_at desc
limit 10;
```

Then inspect the failed fix item:

```sql
select key, type, status, result->'budget' as budget, result->>'next_action' as next_action
from work_items
where run_id = '<run_id>' and type = 'FIX_TEST_FAILURE';
```

Immediate recovery options:

- fork/create a new run with a higher run cost budget
- manually repair the generated test or implementation in the workspace, then rerun validation
- reduce scope before retrying so the fix node has enough budget to run

Do not debug repo auth for this pattern if workspace status is already `SEEDED` and test execution produced a pytest stack trace. The clone path is healthy at that point.

Common generated-test defect:

```text
NameError: name 'ProjectsSectionParser' is not defined
```

If the stack trace points inside a parser class body, inspect the generated test file for accidentally indented test logic inside the class. The class body is executed while the class is being defined, so `parser = ProjectsSectionParser()` inside the class body raises `NameError`. Move the file-reading, parser instantiation, and assertions into a standalone `test_*` function.

## Known recent failure pattern (example)

Observed in project `dde9d488-3942-4fe1-8af5-a36a70f95304` on May 8, 2026:

### Stale worker claimed repo-backed work with old SSH config

Facts:

- Project repository was correctly saved as:
  - `repo_url = https://github.com/abhishek-jha-ai/agentic-ai-test.git`
  - `auth_strategy = public_https`
- `POST /repo/preflight` passed with:
  - `auth_mode = plain`
  - `credential_strategy = anonymous_https`
- Failed run `22f63905-711f-4deb-a3b1-3d0521faaeb1` still showed:
  - `auth_mode=ssh`
  - `selection_reason=explicit_ssh_mode`
- Work item failure stage was `workspace_context`.
- The work item was claimed by stale worker `worker-3c7ad98e`, while newer worker records also existed.

Root cause:

- Historical worker agent rows in RDS remained `ACTIVE`.
- An older worker could still claim work items and execute stale code/config.
- API health and repo preflight were correct, but the work item was not executed by the clean worker.

Fix applied:

- local worker startup now marks existing local active worker agents `INACTIVE` before registering the new worker.
- stale worker rows were manually deactivated in RDS.
- full stack was restarted.

Verification:

- only one recent worker stayed `ACTIVE`
- stale workers had `status = INACTIVE`, `executors = []`, `capabilities = []`
- next run advanced past clone/auth into normal code/test execution

### Recovery context limit after test failure

Earlier observed pattern in the same project:

1. `RUN_TESTS` failed with `SyntaxError` in generated `test_index_html.py`.
2. Recovery `FIX_TEST_FAILURE` then failed with `context_limit_exceeded`.
3. Remaining review/integration/test nodes were canceled as blocked by terminal failure.

### Recovery blocked by cost budget after generated test collection error

Observed in run `0b0df1b3-cc47-4f54-8e51-25b94117a8c8` on May 8, 2026:

Facts:

- Workspace was `SEEDED`.
- Current clean worker `e89e88d1-a953-47c4-aa7f-378dfb036483` claimed the work.
- `RUN_TESTS` failed during pytest collection:
  - `test_index_html.py:276: class ProjectsSectionParser(HTMLParser)`
  - `test_index_html.py:321: parser = ProjectsSectionParser()`
  - `NameError: name 'ProjectsSectionParser' is not defined`
- Recovery was queued:
  - `WORK_ITEM_RECOVERY`
  - `FIX_TEST_FAILURE_1`
- Recovery failed before making a patch because the run exceeded budget:
  - `used_cost_cents = 50.9003`
  - `max_cost_cents = 40.0`
  - `completion_token_cap = 0`
  - `error_kind = run_budget_exhausted`

Root cause:

- The generated test file placed executable parser/assertion logic inside the parser class body instead of in a standalone `test_*` function.
- The runtime recovery policy did spawn a fix node, but execution-contract budget enforcement blocked model work before the fix could be attempted.

Next action:

- fork/create a new run with a higher cost budget or narrower scope
- or manually repair `test_index_html.py`, then rerun `pytest -q`

This is why Mission Control can show several `Blocked` items even when implementation steps are `DONE`.

## Operational notes

- Never paste full connection strings or credentials in tickets.
- Prefer sharing `run_id`, `project_id`, event sequence, and AI stop reason.
- For repeated failures, compare with previous completed run for the same project before changing policies.
