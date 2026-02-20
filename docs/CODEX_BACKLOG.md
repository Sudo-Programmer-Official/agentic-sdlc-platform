# Codex Backlog
Guiding constraints (apply to every task unless overridden):
- Follow repo conventions; keep scope minimal.
- Update docs/tests alongside code.
- Every action should emit a ledger entry where applicable.
- No new dependencies unless explicitly approved.
- Provide verification commands with each change.

## Phase A — Factory Core Hardening

TASK_ID: T-A1-001  
GOAL: Add a DB layer (SQLite for v1) using SQLModel/SQLAlchemy with repositories for projects, runs, tasks, approvals, ledger, and change requests.  
SCOPE:
- Introduce DB module and session management.
- Define ORM models mapped from existing domain models.
- Provide repository interfaces and implementations.  
ACCEPTANCE_CRITERIA:
- API can create/read projects and runs persisted to SQLite.
- Restarting API retains data.
- Unit tests cover repositories.  
FILES_ALLOWED:
- apps/api/app/db/**
- apps/api/app/services/**
- core/src/core/**
- alembic/** (if created)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-A1-002  
GOAL: Migrate registry/state stores to DB-backed implementations.  
SCOPE:
- Replace in-memory stores for projects, runs, tasks, approvals, ledger, changes with DB-backed repos.
- Wire services to use repos via dependency injection.  
ACCEPTANCE_CRITERIA:
- All API endpoints operate on DB data.
- Existing API tests pass with test DB.
- Restart does not lose ledger/tasks.  
FILES_ALLOWED:
- apps/api/app/services/**
- apps/api/app/db/**
- core/src/core/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-A1-003  
GOAL: Add migrations tooling (Alembic) and baseline schema.  
SCOPE:
- Configure Alembic env for SQLModel/SQLAlchemy.
- Create initial migration covering all tables.
- Add make/poetry/script helpers to run migrations.  
ACCEPTANCE_CRITERIA:
- `alembic upgrade head` succeeds from clean checkout.
- Migration reproducibly creates schema used by services.
- Document migration commands in docs/RUNBOOK.md.  
FILES_ALLOWED:
- alembic/**
- apps/api/alembic.ini
- docs/RUNBOOK.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-A1-004  
GOAL: Update API tests to use test DB fixture.  
SCOPE:
- Add ephemeral SQLite fixture for tests.
- Adjust service wiring for test mode.
- Cover create/read flows for projects, runs, approvals, ledger.  
ACCEPTANCE_CRITERIA:
- `pytest` passes with isolated DB per test module or function.
- No test order dependence.  
FILES_ALLOWED:
- apps/api/tests/**
- apps/api/app/db/**
- apps/api/app/services/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Phase B — Agent Runtime Production Shape

TASK_ID: T-B1-001  
GOAL: Implement BedrockAdapter interface (stub OK) aligning agent calls to Bedrock-compatible contract.  
SCOPE:
- Define adapter interface and stub implementation.
- Add config knobs for model, region, credentials source (env).  
ACCEPTANCE_CRITERIA:
- Agents can be constructed with BedrockAdapter without code changes elsewhere.
- Calls log model + timing (even if stubbed).  
FILES_ALLOWED:
- agent/src/agent/**
- apps/api/app/services/**
- docs/ARCHITECTURE.md (brief update)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-B1-002  
GOAL: Add per-task tool permission model (allowed_tools list).  
SCOPE:
- Extend Task model with allowed_tools.
- Enforce at executor entry: block tool calls not whitelisted.
- Log violations to ledger.  
ACCEPTANCE_CRITERIA:
- Task without permission cannot invoke blocked tool.
- Ledger records denial event.
- Tests cover allow/deny paths.  
FILES_ALLOWED:
- core/src/core/models/**
- agent/src/agent/**
- apps/api/app/services/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-B1-003  
GOAL: Add budget tracking per run (tokens/time).  
SCOPE:
- Track token/time budgets on runs and tasks.
- Decrement on execution; halt when exceeded.
- Surface remaining budget in summary endpoint.  
ACCEPTANCE_CRITERIA:
- Exceeding budget sets run status to PAUSED/FAILED per rule and logs ledger entry.
- Summary endpoint shows remaining budget.
- Tests cover budget exhaustion.  
FILES_ALLOWED:
- core/src/core/**
- apps/api/app/services/**
- apps/api/app/api/v1/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-B2-001  
GOAL: Implement DAG scheduler (ready tasks when deps satisfied).  
SCOPE:
- Add scheduler that resolves depends_on and parallel_group.
- Provide API hook execute_tasks_bounded(run_id, cap).  
ACCEPTANCE_CRITERIA:
- Tasks execute only when deps done.
- Ready set is deterministic given status graph.
- Tests cover diamond and cross-branch scenarios.  
FILES_ALLOWED:
- core/src/core/**
- agent/src/agent/**
- apps/api/app/services/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-B2-002  
GOAL: Enforce parallel groups with worker pool cap.  
SCOPE:
- Worker pool honoring cap and parallel_group sequencing.
- Timeout per task.  
ACCEPTANCE_CRITERIA:
- With cap=3, at most 3 tasks run concurrently.
- Parallel groups respected; tasks in later group wait.
- Timeouts mark task FAILED and log.  
FILES_ALLOWED:
- agent/src/agent/**
- core/src/core/**
- apps/api/app/services/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-B2-003  
GOAL: Retry rules for failed tasks.  
SCOPE:
- Add max_retries and backoff to tasks.
- Ledger entries for each retry attempt.  
ACCEPTANCE_CRITERIA:
- Retries stop after configured attempts.
- Final status reflects success/failure after retries.
- Tests cover success-on-retry and exhausting retries.  
FILES_ALLOWED:
- core/src/core/**
- agent/src/agent/**
- apps/api/app/services/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Phase C — GitHub Integration

TASK_ID: T-C1-001  
GOAL: GitHub webhook receiver with signature verification.  
SCOPE:
- Endpoint `/webhooks/github` (POST) verifying HMAC SHA-256.
- Handle at least push, pull_request, issue_comment events (log only).  
ACCEPTANCE_CRITERIA:
- Invalid signature returns 401.
- Valid events stored in ledger/audit.  
FILES_ALLOWED:
- apps/api/app/api/v1/**
- apps/api/app/services/**
- docs/RUNBOOK.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C1-002  
GOAL: Installation token service for GitHub App.  
SCOPE:
- Service to exchange app credentials for installation access token.
- Cache tokens until expiry.  
ACCEPTANCE_CRITERIA:
- Can obtain token for installation ID via config/env.
- Errors surfaced with clear messages; tested with mocked HTTP.  
FILES_ALLOWED:
- apps/api/app/services/github/**
- apps/api/app/core/config.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C1-003  
GOAL: Repo service (branch, commit files, open PR).  
SCOPE:
- Minimal GitHub client methods for create_branch, commit_files, create_pr.
- Uses installation token service.  
ACCEPTANCE_CRITERIA:
- Can open PR with provided file patch in dry-run test (mocked HTTP).
- Errors logged to ledger.  
FILES_ALLOWED:
- apps/api/app/services/github/**
- core/src/core/ledger/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C2-001  
GOAL: Parse PR comments for autopilot commands.  
SCOPE:
- Commands: /autopilot plan, /autopilot run cap=3, /autopilot review, /autopilot override reason=\"...\".
- Dispatch to executor/planner/reviewer services.  
ACCEPTANCE_CRITERIA:
- Comment triggers correct handler; unknown commands ignored politely.
- Responses posted back as PR comment (mocked).  
FILES_ALLOWED:
- apps/api/app/services/github/**
- apps/api/app/api/v1/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C2-002  
GOAL: Post status updates to PR comments.  
SCOPE:
- Utility to format and send status/progress messages.
- Use for planner/executor start/finish.  
ACCEPTANCE_CRITERIA:
- Status comment includes task counts and link to logs.
- Tested with mocked HTTP.  
FILES_ALLOWED:
- apps/api/app/services/github/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C3-001  
GOAL: Publish basic “Governance” GitHub Check (static message OK).  
SCOPE:
- GitHub Checks API call with summary, neutral conclusion by default.  
ACCEPTANCE_CRITERIA:
- PR displays Governance check with summary text.
- Test covers payload formatting.  
FILES_ALLOWED:
- apps/api/app/services/github/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C3-002  
GOAL: Advisory mode for Checks (warnings, not blocking).  
SCOPE:
- Allow config to switch between neutral/success; include warnings list.  
ACCEPTANCE_CRITERIA:
- Advisory outputs warnings without failing check.
- Configurable via env.  
FILES_ALLOWED:
- apps/api/app/services/github/**
- apps/api/app/core/config.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-C3-003  
GOAL: Prepare for “required” mode toggle (future).  
SCOPE:
- Config flag to mark Governance check as required (no-op default).
- Document how to enable in GitHub branch protection.  
ACCEPTANCE_CRITERIA:
- Configurable flag exists; defaults to advisory.
- Docs explain enablement steps.  
FILES_ALLOWED:
- apps/api/app/core/config.py
- docs/GOVERNANCE.md
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Phase D — Hybrid Drift Detection

TASK_ID: T-D1-001  
GOAL: Add rules engine with ~10 drift rules.  
SCOPE:
- Implement rules: new endpoint without tests; auth removed; DB model change w/o migration; cross-module edit w/o ADR; docs changed post-approval → stale, etc.
- Structure rules as pure functions over diff + metadata.  
ACCEPTANCE_CRITERIA:
- Given sample diff, engine returns findings with severity (info/warn/critical).
- Unit tests cover each rule.  
FILES_ALLOWED:
- core/src/core/drift/**
- apps/api/app/services/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-D1-002  
GOAL: Connect drift engine to GitHub PR diff ingestion.  
SCOPE:
- Fetch PR diff, run rules, produce findings.  
ACCEPTANCE_CRITERIA:
- Governance check includes rule findings summary.
- Logs include structured findings for ledger.  
FILES_ALLOWED:
- apps/api/app/services/github/**
- core/src/core/drift/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-D1-003  
GOAL: Emit structured findings + ledger + check summary.  
SCOPE:
- Persist drift findings to ledger/audit.
- Surface in API endpoint for UI drift panel.  
ACCEPTANCE_CRITERIA:
- Ledger records each finding with severity/type.
- API endpoint returns findings for a project/run.
- Tests cover persistence + retrieval.  
FILES_ALLOWED:
- apps/api/app/api/v1/**
- core/src/core/ledger/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-D2-001  
GOAL: Add AI advisory enhancer for drift (non-blocking).  
SCOPE:
- Prompt template to analyze PRD/NFR vs diff.
- Append “AI Insights” section to findings.  
ACCEPTANCE_CRITERIA:
- Advisory text clearly separated from rule findings.
- Safe defaults; can be disabled by config.  
FILES_ALLOWED:
- core/src/core/drift/**
- agent/src/agent/**
- apps/api/app/core/config.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-D2-002  
GOAL: Configurable toggle for AI advisory.  
SCOPE:
- Env/config flag to enable/disable AI insights.  
ACCEPTANCE_CRITERIA:
- Disabled flag skips AI call and UI section.
- Tests cover toggle on/off.  
FILES_ALLOWED:
- apps/api/app/core/config.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Phase E — Deployment Loop (ECS)

TASK_ID: T-E1-001  
GOAL: Dockerfile(s) for API and Web.  
SCOPE:
- Create Dockerfiles for api and web (or combined image with nginx+api).
- Multi-stage builds with minimal runtime image.  
ACCEPTANCE_CRITERIA:
- `docker build` succeeds for both services.
- Images run with env-configurable API base.  
FILES_ALLOWED:
- apps/api/Dockerfile
- apps/web/Dockerfile
- docker-compose.yml (if added)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (smoke via docker run)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-E1-002  
GOAL: Compose for local parity.  
SCOPE:
- docker-compose to run api + web + db.
- Shared network and env examples.  
ACCEPTANCE_CRITERIA:
- `docker compose up` boots all services.
- Healthchecks pass.  
FILES_ALLOWED:
- docker-compose.yml
- docs/RUNBOOK.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (smoke commands)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-E2-001  
GOAL: ECS task definition + ALB + env wiring.  
SCOPE:
- Terraform/CloudFormation or CLI script for ECS service, task def, ALB, target group, listener rules.
- Parameterize env vars/secrets.  
ACCEPTANCE_CRITERIA:
- Deploy script produces running ECS service reachable via ALB DNS.
- Health check passes.  
FILES_ALLOWED:
- infra/ecs/**
- docs/RUNBOOK.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (IaC plan/apply dry-run)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-E2-002  
GOAL: One-command deploy script.  
SCOPE:
- Script (make/poetry/bash) to build, push image, update ECS service.  
ACCEPTANCE_CRITERIA:
- Single command performs build+push+deploy using configured AWS creds.
- Logs show new task revision.  
FILES_ALLOWED:
- infra/ecs/**
- Makefile or scripts/**
- docs/RUNBOOK.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (dry-run/echo mode)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-E2-003  
GOAL: Health and rollout checks.  
SCOPE:
- ALB healthcheck config; deployment circuit-breaker or minHealthyPercent.
- Post-deploy smoke test hitting /health.  
ACCEPTANCE_CRITERIA:
- Failed deploy rolls back automatically.
- Smoke test command documented.  
FILES_ALLOWED:
- infra/ecs/**
- docs/RUNBOOK.md
- apps/api/app/main.py (if health tweak)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (scripted smoke)  
OUTPUT:
- PR-ready changes + verification steps

## Phase F — Mission Control UX

TASK_ID: T-F1-001  
GOAL: Run Center card (start/pause/resume/cancel).  
SCOPE:
- UI card in Mission Control for run lifecycle controls.
- Wire to API endpoints.  
ACCEPTANCE_CRITERIA:
- Buttons reflect current run status; disabled appropriately.
- Actions update run status and context.  
FILES_ALLOWED:
- apps/web/src/views/MissionControl.vue
- apps/web/src/components/**
- apps/api/app/api/v1/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-F1-002  
GOAL: Task queue view with filters.  
SCOPE:
- Add filters (status/agent/group) and search.
- Paginate if needed.  
ACCEPTANCE_CRITERIA:
- Filtering works client-side on loaded tasks.
- UX keeps Mission Control performant.  
FILES_ALLOWED:
- apps/web/src/components/**
- apps/web/src/views/MissionControl.vue  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (component/unit)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-F1-003  
GOAL: Drift findings panel in Mission Control.  
SCOPE:
- Consume API drift endpoint; render grouped by severity.
- Link to GitHub check if available.  
ACCEPTANCE_CRITERIA:
- Findings visible when present; empty state clear.
- Severity badge consistent with status system.  
FILES_ALLOWED:
- apps/web/src/components/**
- apps/web/src/views/MissionControl.vue
- apps/api/app/api/v1/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-F1-004  
GOAL: PRD editor + approval dialog.  
SCOPE:
- UI to edit PRD doc and request approval.
- Wire to API approvals.  
ACCEPTANCE_CRITERIA:
- Save updates doc artifact; approval request updates stage/ledger.
- Validation for required fields.  
FILES_ALLOWED:
- apps/web/src/views/**
- apps/web/src/components/**
- apps/api/app/api/v1/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-F2-001  
GOAL: Define core UI tokens (spacing, typography, radius, colors).  
SCOPE:
- Central theme file; apply to buttons/badges/panels.  
ACCEPTANCE_CRITERIA:
- Tokens consumed in main components.
- Document tokens in UI_SPEC.md.  
FILES_ALLOWED:
- apps/web/src/index.css
- apps/web/src/theme/**
- docs/UI_SPEC.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (visual/story if available)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-F2-002  
GOAL: Element Plus theme override.  
SCOPE:
- Create theme override file mapping tokens to Element Plus vars.  
ACCEPTANCE_CRITERIA:
- Buttons, inputs, tags reflect custom theme.
- No regressions in dark/light handling.  
FILES_ALLOWED:
- apps/web/src/theme/**
- apps/web/src/main.ts  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (snapshot/visual)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: T-F2-003  
GOAL: Standardize status badges across UI.  
SCOPE:
- Single badge component with variants (stage/run/task/severity).
- Replace ad-hoc tags/badges.  
ACCEPTANCE_CRITERIA:
- All statuses use unified component.
- Props cover color/text/icon; documented.  
FILES_ALLOWED:
- apps/web/src/components/**
- apps/web/src/views/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (component/unit)  
OUTPUT:
- PR-ready changes + verification steps
