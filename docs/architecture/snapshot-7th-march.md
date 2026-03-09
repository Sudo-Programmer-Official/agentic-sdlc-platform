# Architecture Snapshot - March 7, 2026

## Executive Summary

This repo is a modular monolith in structure, but the platform is currently split across two overlapping implementations:

- a legacy in-memory SDLC/orchestration backend under `apps/api/app/api/v1/routes.py`
- a newer SQLAlchemy/Postgres-backed persistence and execution backend under `apps/api/app/api/v1/persistence.py`

Both are mounted into the same FastAPI app in `apps/api/app/main.py`. That split is the main architectural fact driving the current gaps: the database model is ahead of some frontend pages, the execution engine is designed but not stable, and several "agentic" pieces are still placeholders or stubs.

Status legend:

- Implemented: present and materially usable
- Partial: present but inconsistent, incomplete, or unstable
- Missing: not implemented or explicitly stubbed

## 1. Folder Structure

| Path | Purpose | Status | Notes |
| --- | --- | --- | --- |
| `apps/api` | FastAPI app, Alembic, SQLAlchemy models, runtime engine, tests | Implemented | Main backend lives here |
| `apps/web` | Vue 3 SPA, router, views, API clients | Implemented | Main frontend lives here |
| `agent` | Agent prompts and runtime agent implementations | Partial | Only a small subset is real |
| `core` | Shared SDLC/domain models, state machine, approvals, contracts | Implemented | Used mainly by legacy/original backend model |
| `docs` | Architecture docs, product notes, snapshots | Implemented | Mixed design docs and repo snapshots |
| `infra` | Deployment scaffolding | Missing | Mostly placeholder content |
| `scripts` | Smoke/eval helper scripts | Partial | Useful for local checks, not a full ops layer |
| `.github` | CI/CD workflow definitions | Partial | Workflow exists, but platform is not deployment-complete |

## 2. Backend Architecture

| Subsystem | Status | Current State | Main Gap |
| --- | --- | --- | --- |
| FastAPI app shell | Implemented | App wiring and router mounting exist | None at the shell layer |
| Legacy SDLC API | Partial | In-memory project, requirements, approvals, runs, changes, audit flows exist | Not aligned with DB-backed app |
| Persistence API | Partial | DB-backed projects, docs, tasks, runs, work items, lifecycle, impact endpoints exist | Some summary/metrics/history endpoints are stubbed |
| Shared domain core | Implemented | Rich SDLC model and transition rules exist in `core` | Not fully reflected in DB-backed workflow |
| Stage model alignment | Missing | Legacy flow uses detailed SDLC stages; persistence flow uses `INTAKE -> PLAN -> RUN -> EVALUATE` | Two workflow vocabularies are active at once |
| Task generation and traceability | Partial | Task regen, artifact graph, impact preview, lifecycle scoring are present | Not consistently surfaced across product flows |
| Multi-tenancy | Partial | Tenant model and `tenant_id` propagation exist | Schema/model drift remains |

Key architectural observation:

- The backend is not one coherent platform yet. It is one process exposing two backend generations in parallel.

## 3. Frontend Pages

| Page | Route Status | Backend Binding | Notes |
| --- | --- | --- | --- |
| `WorkspaceHome.vue` | Implemented | DB-backed `/store/projects` | Functional entry point |
| `ProjectOverview.vue` | Implemented | Mostly DB-backed `/store/...` APIs | Most complete page in the repo |
| `Requirements.vue` | Partial | Mixes legacy `/projects/{id}/requirements-graph` with `/store/...` summary data | Likely inconsistent for DB-created projects |
| `MissionControl.vue` | Partial | Uses legacy `/projects/...`, `/runs/...`, `/changes/...` APIs | Rich UI, but not aligned with newer execution backend |
| `Approvals.vue` | Missing | Placeholder | No meaningful workflow yet |
| `AgentRuns.vue` | Missing | Placeholder | No real runs view yet |
| `SdlcTimeline.vue` | Missing | Placeholder | No real timeline implementation yet |

Frontend conclusion:

- The UI is centered around `ProjectOverview`.
- The rest of the navigation still reflects mixed-era backend assumptions.

## 4. Existing Agents

| Agent / Executor | Status | What Exists | Gap |
| --- | --- | --- | --- |
| `RequirementsAgent` | Implemented | Produces `PRD.md`, `USER_STORIES.md`, `ACCEPTANCE.md` | Limited scope |
| `PlannerAgent` | Implemented | Produces `PLAN.json` and planned task labels | Downstream agent execution is not fully realized |
| Requirements intelligence | Partial | Deterministic extraction logic exists | Not a real LLM-driven pipeline |
| Bedrock adapter | Missing | Stubbed adapter file exists | No real Bedrock integration |
| Workspace manager | Missing | Placeholder branch/worktree/diff management | No production Git workspace flow |
| Runtime executors: `dummy`, `codex`, `test` | Partial | Registry exists and executor types are defined | `codex` path creates startup/test friction |

Important distinction:

- Planner output mentions roles like `UI_AGENT`, `BACKEND_AGENT`, `ARCH_AGENT`, `SECURITY_AGENT`, and `PERF_AGENT`.
- Those are planned task labels, not fully implemented runtime agent classes.

## 5. Missing Components

| Component | Status | Evidence |
| --- | --- | --- |
| Real Bedrock/AWS execution | Missing | Repo still describes itself as foundation/skeleton |
| Legacy `trigger_agent_run` endpoint | Missing | Explicit `501` in legacy routes |
| Full Git branch/worktree/diff workflow | Missing | `workspace_manager.py` is still placeholder code |
| Stable project summary/metrics/history | Partial | Persistence endpoints return defaults or empty lists in key places |
| Complete multi-tenant schema | Partial | `TenantMember` model exists, but table migration is absent |
| Model/migration parity for tenant flags | Partial | `Tenant.system_reserved` exists in model but not in migration |
| Unified frontend/backend contract | Missing | Some pages use `/store/...`; others use legacy `/projects/...` |
| Deployment-ready infra | Missing | `infra` remains mostly placeholder material |

## 6. Database Schema

Overall status: Partial

The relational schema is one of the stronger parts of the repo. Core operational tables and execution tables exist, but the tenant layer is not fully migrated and some application features are ahead of finished API behavior.

| Domain | Status | Main Tables |
| --- | --- | --- |
| Project and document lineage | Implemented | `projects`, `documents`, `tasks` |
| Artifact traceability | Implemented | `artifacts`, `traces`, `approvals`, `activity_logs` |
| Execution runtime | Implemented | `runs`, `run_events`, `work_items`, `work_item_edges`, `work_item_artifacts` |
| Agent/runtime memory | Implemented | `agents`, `project_memory`, `run_memory` |
| Multi-tenancy | Partial | `tenants` plus `tenant_id` on operational tables; `tenant_members` missing from migrations |

Schema observations:

- The migration history is substantial and shows active design work.
- Indexing and constraints are already present for several important paths.
- The schema is more mature than the end-to-end product integration.

## 7. Execution Engine Status

Overall status: Partial

What exists:

- DAG generation is defined in `apps/api/app/runtime/dag.py`
- orchestration exists in `apps/api/app/runtime/orchestrator.py`
- external mode is the default in `apps/api/app/core/config.py`
- scheduler and worker services exist for external execution
- run, event, and work-item tables are already in the schema

Expected execution path:

- `PLAN_DAG`
- `CODE_BACKEND`
- `CODE_FRONTEND`
- `WRITE_TESTS`
- `REVIEW_DIFF`
- `RUN_TESTS`
- `REVIEW_INTEGRATION`

Current blockers:

| Blocker | Status | Notes |
| --- | --- | --- |
| App import requires live executor setup | Partial | Test collection fails because `CodexExecutor` eagerly builds an OpenAI client |
| Persistence router import error | Missing | Import fails with undefined `get_tenant_id` reference |
| Orchestrator import bug | Missing | `update_work_item_status` is used without import |
| Executor call contract mismatch | Missing | Orchestrator passes executor args in the wrong order |
| Worker service import bug | Missing | `exists` and `and_` are used without import |
| Runtime test coverage | Partial | Tests exist around persistence and graph behavior, not robust engine execution |

Validation performed:

- `apps/api/.venv/bin/pytest apps/api/tests -q`
- result: collection failed due to eager `CodexExecutor` initialization and API-key dependency

Execution conclusion:

- The engine is architected, schema-backed, and visibly under active construction.
- It is not yet operational end-to-end.

## Repo-Level Assessment
deddAPI model instead of running legacy and persistence flows in parallel.
2. Align all frontend pages to the same backend contract, ideally the DB-backed `/store/...` layer.
3. Make the execution engine import-safe and testable without live external credentials.
4. Close schema/model drift in multi-tenancy before deeper tenant features are built.
5. Replace placeholder agent/Git/AWS components with real runtime integrations.
