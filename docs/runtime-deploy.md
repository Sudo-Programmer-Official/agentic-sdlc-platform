# Runtime Deployment Guide (factory-safe)

## Services
- api: FastAPI app (N replicas)
- scheduler: single replica (python -m app.runtime.scheduler_service)
- worker: M replicas (python -m app.runtime.worker_service)

## Env vars (common)
- DATABASE_URL
- RUNTIME_MODE: embedded | external (prod: external)
- MAX_WORKITEM_CONCURRENCY: default 3

## Modes
- embedded: orchestrator executes work items in-process (dev only)
- external: orchestrator does NOT execute; workers execute via claim/complete; scheduler handles requeue/finalize/lifecycle
- external fallback: if no live worker heartbeats are present, the orchestrator falls back to embedded execution so runs do not remain queued forever on API-only deployments

## Start commands
- API: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Scheduler: `python -m app.runtime.scheduler_service`
- Worker: `python -m app.runtime.worker_service`

## Replica guidance
- api: scale horizontally
- scheduler: 1 replica
- worker: scale based on throughput; at least 2–5 for parallelism

## Failure behavior
- scheduler requeues expired leases and finalizes runs; workers only execute
- conditional updates guard state; duplicates return 409

## Smoke check (external mode)
1) set RUNTIME_MODE=external
2) start scheduler + workers
3) create run -> DAG created, workers claim/execute, run finalizes, lifecycle recomputes
