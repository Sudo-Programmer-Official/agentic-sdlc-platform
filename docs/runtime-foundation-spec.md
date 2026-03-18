# Runtime Foundation Spec (v1) — Prompt2PR Software Factory

See also: `docs/agent-runtime-vision-roadmap.md`, `docs/human-in-the-loop-runtime-roadmap.md`, `docs/run-console-product-spec.md`, and `docs/network-and-recovery-architecture.md`. The roadmap and spec documents are the current product-level reference for durable bootstrap, truthful runtime UX, operator steering, concrete Mission Control surfaces, and the lease-safe recovery model needed to expose execution truth. This document remains the narrower runtime implementation baseline.

## Goal
Turn the current “manual run controls” into a real execution runtime that is:
- deterministic  
- observable  
- agent-pluggable  
- guarded by state machines  
- audit-friendly  

Agents must never mutate core tables directly. They act only through the runtime.

## Scope (v1)
Implement:
1. Event Log (immutable audit stream)  
2. TaskExecutor interface (agent plug-in point)  
3. RunOrchestrator (drives tasks + run state)  
4. Orchestrator-driven transitions (remove manual “COMPLETE” as primary mechanism)  
5. DummyExecutor (keeps UI usable end-to-end)  

Out of scope (v1):
- multi-worker distributed execution  
- retries/backoff beyond simple  
- task DAG scheduling (simple order only)  
- task diff/churn analytics (v2)  

## Data Model
### A) run_events (new, append-only)
Purpose: audit, replay, debugging, lifecycle explainability.  
Columns: id (UUID PK), project_id (FK), run_id (FK), task_id nullable (FK), event_type text, ts timestamptz default now(), actor_type SYSTEM|USER|AGENT, actor_id nullable, message text nullable, payload jsonb nullable, correlation_id nullable.  
Indexes: (run_id, ts), (project_id, ts), (task_id, ts) partial where task_id not null.  
Event types (minimum): RUN_CREATED, RUN_STARTED, RUN_COMPLETED, RUN_FAILED, RUN_CANCELED, TASK_QUEUED, TASK_STARTED, TASK_COMPLETED, TASK_FAILED, TASK_SKIPPED, STAGE_TRANSITION_REQUESTED, STAGE_TRANSITIONED, LIFECYCLE_SCORED (optional).  
Rules: append-only; every run/task status change emits an event.

### B) tasks updates
Status enum: PENDING | RUNNING | DONE | FAILED | SKIPPED  
run_id nullable FK (already planned)  
started_at, finished_at timestamptz nullable  
last_error text nullable  
result_payload jsonb nullable  
Rule: orchestrator sets these fields.

### C) runs updates
Status: QUEUED | RUNNING | COMPLETED | FAILED | CANCELED  
started_at, finished_at  
trigger: USER | SYSTEM | AGENT  
summary_payload jsonb nullable  
Rule: orchestrator sets status/time fields; API triggers orchestrator.

## Runtime Architecture
### 1) TaskExecutor Contract (`apps/api/app/runtime/executor.py`)
```python
class TaskResult(TypedDict):
    status: Literal["DONE", "FAILED", "SKIPPED"]
    message: str
    payload: dict

class TaskExecutor(Protocol):
    name: str  # "dummy", "codex", "lint", etc.

    async def execute(self, task: Task, context: "RunContext") -> TaskResult:
        ...
```

### 2) RunContext (`apps/api/app/runtime/context.py`)
Holds project_id, run_id, workspace/repo path (if any), API keys/agent config (optional), snapshots of docs/tasks/traces ids (optional). v1 can stay minimal.

### 3) RunOrchestrator (`apps/api/app/runtime/orchestrator.py`)
Responsibilities:
- validate run can start (guards)
- transition run status: QUEUED → RUNNING → COMPLETED/FAILED/CANCELED
- select tasks to run (v1: all tasks for project ordered by created_at)
- for each task: mark RUNNING + ts, emit TASK_STARTED, call executor, mark DONE/FAILED/SKIPPED + payload/last_error, emit TASK_COMPLETED/FAILED
- emit run completion event and update run fields
- after completion: optionally recompute lifecycle score + emit LIFECYCLE_SCORED

Rule: UI is not the source of truth for completion; run endpoint triggers orchestrator logic.

## API Surface Changes (v1)
- **POST** `/api/v1/store/projects/{project_id}/runs`  
  Creates run in QUEUED and immediately kicks orchestrator in background (or POST `/runs/{run_id}/start` if you prefer explicit start). Returns run quickly.  
- **PATCH** `/runs/{run_id}/status`  
  v1: only allows CANCELED from user; other transitions are orchestrator-owned.  
- **GET** `/api/v1/store/runs/{run_id}/events` (optional but recommended) and `/projects/{project_id}/events?limit=...`

## Stage Machine Integration
Current guards stay:
- INTAKE → PLAN needs docs  
- PLAN → RUN needs tasks  
- RUN → EVALUATE needs ≥1 COMPLETED run and no RUNNING run  

Runtime rule: when a run starts, ensure project stage is RUN (or 409 with allowed_transitions).

## Dummy Executor (v1)
Purpose: prove end-to-end run pipeline.  
Behavior: for each task, if title contains “fail” → FAILED else DONE; payload `{"executor":"dummy","took_ms":123,"notes":"Simulated execution"}`. Provides durations and score effects without AI.

## End-to-End Flow (Acceptance)
1. Fresh project → lifecycle-score returns empty-state 200.  
2. Doc + tasks, no runs → PLAN→RUN allowed; lifecycle shows execution neutral + “No runs executed” warning.  
3. Start run → orchestrator sets RUNNING; tasks move to RUNNING then DONE/FAILED; run → COMPLETED/FAILED; events recorded; lifecycle updates.  
4. RUN→EVALUATE blocked until a COMPLETED run exists and no RUNNING runs; passes once completed.

## Implementation Order (checklist)
1. Add run_events migration + model + writer helper.  
2. Add runtime module with TaskExecutor + DummyExecutor.  
3. Implement RunOrchestrator with proper DB session mgmt.  
4. Wire API: start run triggers orchestrator (create run or explicit start).  
5. Add GET /runs/{id}/events.  
6. UI: replace manual “Complete Run” as primary; show events + live status polling.  

## Non‑negotiables
- Orchestrator is the only writer of task/run status.  
- Agents plug in via TaskExecutor only.  
- Every state change emits an immutable event.  
- All failures return error_id and are traceable via correlation id in events/logs.  
