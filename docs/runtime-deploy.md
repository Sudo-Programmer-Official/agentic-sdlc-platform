# Runtime Deployment Guide (factory-safe)

## Services
- api: FastAPI app (N replicas)
- scheduler: single replica (python -m app.runtime.scheduler_service)
- worker: M replicas (python -m app.runtime.worker_service)

## Env vars (common)
- DATABASE_URL
- RUNTIME_MODE: embedded | external (prod: external)
- MAX_WORKITEM_CONCURRENCY: default 3

## Repo-backed runtime env
- api always requires:
  - GITHUB_APP_ID
  - GITHUB_PRIVATE_KEY
  - RUNTIME_GIT_AUTH_MODE=github_app_https
- worker requires the same values only when you actually deploy a separate worker service
- optional for clone auth, required for webhook verification:
  - GITHUB_WEBHOOK_SECRET
- scheduler does not need GitHub App secrets because it does not prepare workspaces or execute repo mutations

Use [ecs-runtime-container-env.example.json](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/infra/deploy/ecs-runtime-container-env.example.json) as the ECS task-definition template for these values.

## Modes
- embedded: orchestrator executes work items in-process (dev only)
- external: orchestrator does NOT execute; workers execute via claim/complete; scheduler handles requeue/finalize/lifecycle
- external fallback: if no live worker heartbeats are present, the orchestrator falls back to embedded execution so runs do not remain queued forever on API-only deployments

## API-only deployment

If your deployed shape is only `web + api`, repo-backed runs can still work.

- the API container must have `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, and `RUNTIME_GIT_AUTH_MODE=github_app_https`
- the API process handles workspace prep and embedded fallback execution when no worker heartbeats are present
- you do not need to create a separate worker service just because the repo contains worker code
- add a worker service only when you intentionally want runtime execution split out of the API process

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

## Startup verification
- API startup should log:
  - `Starting API build=... sha=... env=production prefix=/api/v1 runtime_mode=external`
  - `Runtime tool availability git=/usr/bin/git`
  - `GitHub integration env app_id_present=True private_key_present=True webhook_secret_present=...`
- Worker startup should log:
  - `Starting worker build=... sha=... runtime_mode=external`
  - `Worker runtime tool availability git=/usr/bin/git`
  - `Worker GitHub integration env app_id_present=True private_key_present=True webhook_secret_present=...`
- Repo-backed workspace prep should log:
  - `adapter=GitHubAppAdapter`
  - `auth_mode=github_app_https`
  - `token_generated=True`

## Rollout order
1. Update the API task definition env/secrets.
2. If you deploy a separate worker service, update its task definition env/secrets with the same GitHub App values.
3. Deploy the changed services and wait for old tasks to drain.
4. Confirm the relevant startup verification lines above before rerunning a smoke task.
