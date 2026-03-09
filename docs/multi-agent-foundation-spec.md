# Multi-Agent Foundation Spec (Phase 3)

Status: Proposed  
Goal: Enable parallel execution of specialized agents/executors via a WorkItem DAG per Run, with deterministic observability (events), persistence (DB), and scalable concurrency (worker pool).  
Non-goals (Phase 3): advanced long-term memory embeddings, tool sandboxing, code merges, PR automation.

---

## 1) Core Concepts

**Run**  
Execution episode for a Project. Already exists (runs table, run events, orchestrator owns RUNNING/COMPLETED/FAILED).

**WorkItem (new)**  
Unit of parallelism (not Task). WorkItems form a DAG and are executed by Agents via Executors. Examples: PLAN_DAG, GENERATE_BACKEND_ENDPOINTS, WRITE_TESTS, REVIEW_INTEGRATION, FIX_FAILED_TESTS.

**Agent**  
Logical worker with capabilities and concurrency. Agents claim WorkItems, produce artifacts, write memory, emit events. They do not “chat.”

**Memory**  
Structured state across project/run/work. Phase 3: DB-first (no vector DB yet).

---

## 2) Data Model (DB)

### 2.1 work_items (new)
- id UUID PK  
- project_id UUID NOT NULL FK projects(id)  
- run_id UUID NOT NULL FK runs(id) ON DELETE CASCADE  
- type TEXT NOT NULL (PLAN, CODE, TEST, REVIEW, FIX, DOC, DEPLOY)  
- key TEXT NULL (stable identifier, e.g., backend:endpoints)  
- status TEXT NOT NULL DEFAULT 'QUEUED' (QUEUED, CLAIMED, RUNNING, DONE, FAILED, CANCELED, SKIPPED)  
- priority INT NOT NULL DEFAULT 0  
- executor TEXT NOT NULL DEFAULT 'dummy' (maps to executor registry)  
- assigned_agent_id UUID NULL FK agents(id)  
- attempt INT NOT NULL DEFAULT 0  
- max_attempts INT NOT NULL DEFAULT 3  
- lease_expires_at TIMESTAMPTZ NULL (for distributed locking)  
- depends_on_count INT NOT NULL DEFAULT 0 (derived for scheduling)  
- payload JSONB NOT NULL DEFAULT '{}'::jsonb  
- result JSONB NOT NULL DEFAULT '{}'::jsonb  
- started_at TIMESTAMPTZ NULL  
- finished_at TIMESTAMPTZ NULL  
- last_error TEXT NULL  
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()  
- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()  

Indexes:  
- (run_id, status, priority DESC)  
- (project_id, run_id)  
- (lease_expires_at)  
- (assigned_agent_id)

### 2.2 work_item_edges (new)
- id UUID PK  
- run_id UUID NOT NULL FK runs(id) ON DELETE CASCADE  
- from_work_item_id UUID NOT NULL FK work_items(id) ON DELETE CASCADE  
- to_work_item_id UUID NOT NULL FK work_items(id) ON DELETE CASCADE  
Constraints: unique (from_work_item_id, to_work_item_id), disallow self-edge  
Indexes: (run_id, to_work_item_id), (run_id, from_work_item_id)

### 2.3 agents (new)
- id UUID PK  
- name TEXT NOT NULL  
- kind TEXT NOT NULL (planner, builder, tester, reviewer, etc.)  
- executors JSONB NOT NULL DEFAULT '["dummy"]'::jsonb  
- capabilities JSONB NOT NULL DEFAULT '{}'::jsonb  
- max_concurrency INT NOT NULL DEFAULT 1  
- status TEXT NOT NULL DEFAULT 'ACTIVE' (ACTIVE, DRAINING, DISABLED)  
- last_heartbeat_at TIMESTAMPTZ NULL  
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()  
Index: (status, last_heartbeat_at)

### 2.4 Memory tables (Phase 3 minimal)
- project_memory: id, project_id, key, value (jsonb), source, created_at, unique(project_id, key)  
- run_memory: id, run_id, key, value (jsonb), created_at, unique(run_id, key)  
- work_item_artifacts: id, work_item_id, type, uri?, payload jsonb, created_at

---

## 3) Events (reuse run_events)

Run-level: WORK_DAG_CREATED, WORK_DAG_INVALID, SCHEDULER_TICK, RUN_BLOCKED, RUN_UNBLOCKED  
WorkItem-level: WORK_ITEM_CREATED, WORK_ITEM_CLAIMED, WORK_ITEM_STARTED, WORK_ITEM_DONE, WORK_ITEM_FAILED, WORK_ITEM_RETRIED, WORK_ITEM_CANCELED, WORK_ITEM_SKIPPED, WORK_ITEM_LEASE_EXPIRED  

Payloads include work_item_id, type, executor, attempt, agent_id, prev/new status, and errors where applicable. Order by (ts, id).

---

## 4) API Surface (minimal Phase 3)

### WorkItems
- GET /projects/{project_id}/runs/{run_id}/work-items
- GET /work-items/{work_item_id}
- GET /runs/{run_id}/work-dag (nodes + edges)

### Agent registration (dev/local)
- POST /agents/register {name, kind, executors, max_concurrency}
- POST /agents/{agent_id}/heartbeat

### Scheduler/worker actions
- POST /agents/{agent_id}/claim {limit:1} → claims runnable items (deps done, status QUEUED, sets lease & CLAIMED)
- POST /work-items/{id}/status {status:"RUNNING"} (optional)
- POST /work-items/{id}/complete {result, artifacts}
- POST /work-items/{id}/fail {error, retry:true|false}
Retry: if retry and attempt < max_attempts → status QUEUED, attempt++ else FAILED.

---

## 5) Scheduler + Orchestrator

RunOrchestrator changes:
- On run start: generate WorkItem DAG, emit WORK_DAG_CREATED.
- Scheduler loop (embedded worker mode) ticks every N seconds:
  - release expired leases (emit WORK_ITEM_LEASE_EXPIRED)
  - find runnable QUEUED items (deps satisfied, priority)
  - execute with bounded semaphore; pick executor by work_item.executor
  - on success → DONE + artifacts; on error → retry or FAILED
- Run completion:
  - COMPLETED if all terminal nodes DONE/SKIPPED
  - FAILED if any critical node FAILED
  - CANCELED if cancellation requested

Concurrency:  
- Enforce MAX_CONCURRENT_WORK_ITEMS per run; respect agent max_concurrency in external worker mode.

---

## 6) Work DAG Generation (v1 template)

Inputs: documents, tasks, run config.  
Template nodes: PLAN_DAG → CODE_BACKEND, CODE_FRONTEND → WRITE_TESTS → REVIEW_INTEGRATION  
Terminal: REVIEW_INTEGRATION  
If no documents: fail DAG with WORK_DAG_INVALID (or minimal PLAN only).  
If no tasks: still allow PLAN_DAG; produce “no tasks” artifact.

---

## 7) Executor Contract (work-item aware)

Executors accept a work_item, not just a task.

```python
class Executor(Protocol):
    key: str
    async def execute(self, ctx: RuntimeContext, work_item: WorkItem) -> ExecutorResult: ...
```

ExecutorResult: status (DONE/FAILED/SKIPPED), result_payload json, artifacts list, warnings list.  
RuntimeContext: project_id, run_id, session factory, event logger, memory helpers, config (timeouts later).  
CodexExecutor v1 can return placeholder payloads; PLAN writes run_memory plan_summary.

---

## 8) UI (Phase 3 minimal)

- Runs panel shows executor used, events link, WorkItems progress (done/total + list).  
- Mission Control gating unchanged (stage RUN, run exists).  
- Optional: work-dag visualization (later).

---

## 9) Failure Modes & Guarantees

- Determinism: all transitions stored; events ordered by (ts, id).  
- Lease safety: CLAIM sets lease_expires_at; expired leases requeue.  
- Retry: attempt/max_attempts; WORK_ITEM_RETRIED event.  
- Cancellation: run cancel → queued items canceled; running best-effort (executor cancellation later).

---

## 10) Migration Plan

Add migrations for:  
1) work_items + work_item_edges  
2) agents  
3) memory tables (project_memory, run_memory, work_item_artifacts)

---

## 11) Implementation Order

1) DB: work_items + edges migration  
2) DAG generator (template)  
3) WorkItem endpoints (list/get/dag)  
4) Embedded worker scheduler in orchestrator (bounded concurrency)  
5) Events for workitem transitions  
6) UI: show workitems progress per run  
7) Optional: agents table + claim API (for external workers)

---

## 12) Acceptance Tests (smoke)

1) create run → RUN_CREATED + WORK_DAG_CREATED events  
2) work-items visible via GET …/work-items  
3) scheduler runs: parallel items (backend+frontend) go RUNNING → DONE  
4) REVIEW_INTEGRATION DONE → run COMPLETED  
5) failure triggers retries then FAILED → run FAILED  
6) lease expiry requeues item after TTL  
7) lifecycle score updates after run completion (existing behavior)
