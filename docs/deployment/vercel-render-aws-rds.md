# Vercel + Render + AWS RDS Deployment Runbook

This runbook is the production deployment path for:

- Frontend: Vercel (`apps/web`)
- Backend runtime: Render (`api`, `scheduler`, `worker`)
- Database: AWS RDS Postgres

## 1. Target architecture

- Vercel serves the SPA and points to `VITE_API_BASE=https://api.<your-domain>/api/v1`.
- Render runs three backend services from `apps/api/Dockerfile`:
  - API web service (`uvicorn app.main:app`)
  - Scheduler worker (`python -m app.runtime.scheduler_service`)
  - Runtime worker (`python -m app.runtime.worker_service`)
- AWS RDS remains the system-of-record database.

## 2. Why all 3 backend services are needed

This codebase is queue-based in `external` runtime mode:

- API handles requests, orchestration, and fallback execution
- Scheduler handles lease requeue/finalization/lifecycle progression
- Worker executes queued runtime work items

API-only works as fallback, but for live reliability and multi-job throughput use all 3.

## 3. Prerequisites

1. RDS endpoint reachable from Render with TLS enabled.
2. Production DB user with least privileges.
3. GitHub App values available if repo-backed runs are enabled:
   - `GITHUB_APP_ID`
   - `GITHUB_PRIVATE_KEY`
   - `GITHUB_WEBHOOK_SECRET` (required for webhook verification)
4. OpenAI API key available (`OPENAI_API_KEY`).

## 4. Render service blueprint

Use the checked-in blueprint:

- [render.yaml](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/infra/deploy/render/render.yaml)

Deploy it via Render Blueprint so all 3 services are created from one manifest.

## 5. Required Render env vars

Set these in Render where marked `sync: false`:

- `DATABASE_URL` = `postgresql+asyncpg://<user>:<pass>@<rds-endpoint>:5432/<db>?sslmode=require`
- `OPENAI_API_KEY`
- `GITHUB_APP_ID` (API + worker)
- `GITHUB_PRIVATE_KEY` (API + worker)
- `GITHUB_WEBHOOK_SECRET` (API + worker)
- `GITHUB_ALLOWED_ORG` (optional guard)

Important:

- Keep `RUNTIME_MODE=external` in production.
- Keep `RUN_MIGRATIONS_ON_STARTUP=1` only on API, `0` on scheduler/worker.

## 6. Vercel configuration

Set Vercel project root to `apps/web` and define:

- `VITE_API_BASE=https://api.<your-domain>/api/v1`

Optional custom domain:

- `app.<your-domain>` -> Vercel
- `api.<your-domain>` -> Render API web service

## 7. Safe cutover sequence

1. Deploy Render API only, keep old frontend/API live.
2. Confirm API health endpoint returns `200` at `/health`.
3. Deploy scheduler and worker services.
4. Validate worker heartbeats in Mission Control / Operator dashboards.
5. Point Vercel `VITE_API_BASE` to new Render API domain.
6. Release Vercel production deployment.
7. Run a smoke run with a small task and verify:
   - run becomes `QUEUED` -> `RUNNING` -> terminal state
   - work items are claimed/completed by worker
   - scheduler finalization happens (no stuck leases)

## 8. Non-breaking validation checklist

1. `GET /health` returns `{"status":"ok"}`.
2. API startup logs include runtime mode and GitHub env presence.
3. Worker startup logs include git tool availability and GitHub env presence.
4. A test run does not remain indefinitely in `QUEUED`.
5. CORS allows the production Vercel domain.
6. DB migrations are applied once by API startup.

## 9. Rollback plan

1. Keep previous API endpoint and Vercel deployment ready.
2. If runtime jobs fail after cutover:
   - roll back Vercel to previous deployment
   - switch API DNS/env back to previous backend
3. Do not change DB schema manually during rollback.
4. Fix env/config in Render, redeploy, and retry smoke tests.

## 10. Post-go-live recommendations

1. Scale baseline:
   - API: 1-2 instances
   - Scheduler: exactly 1 instance
   - Worker: start 1, scale to 2+ for throughput
2. Add monitoring/alerts on:
   - API health failures
   - worker crash loops
   - growing queued work item count
3. Set cost guardrails:
   - low worker count off-hours
   - budget alerts in Render and AWS

