# Local Testing Now, Cloud Deploy Later

This runbook captures the current approach:

1. Keep validating features in local dev.
2. Prepare cloud deployment inputs now.
3. Deploy to Vercel + Render later when stable.

## Current Mode (Local First)

Use local stack for daily development and verification.

From repo root:

```bash
./scripts/dev_stack.sh
```

Or via Docker services:

```bash
docker compose up -d --build db api scheduler worker
docker compose ps
docker compose logs -f api scheduler worker db
```

## Firebase Web Config (Local + Future Vercel)

Current frontend env in `apps/web/.env`:

```env
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=...
VITE_FIREBASE_APP_ID=...
VITE_FIREBASE_STORAGE_BUCKET=...
VITE_FIREBASE_MESSAGING_SENDER_ID=...
VITE_FIREBASE_MEASUREMENT_ID=...
```

Notes:
- `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_APP_ID` are required for sign-in.
- Storage/messaging/measurement variables are optional today, but safe to keep.

## Planned Cloud Topology (Deploy Later)

Reference: [`docs/runtime-deploy.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/runtime-deploy.md)

- `web` -> Vercel
- `api` -> Render Web Service
- `scheduler` -> Render Background Worker (1 replica)
- `worker` -> Render Background Worker (2+ replicas)

Runtime mode target:

```env
RUNTIME_MODE=external
```

## Vercel Plan (Web)

Project settings:
- Root Directory: `apps/web`
- Build Command: `npm run build`
- Output Directory: `dist`

Environment variables to add in Vercel:
- `VITE_API_BASE_URL`
- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_APP_ID`
- `VITE_FIREBASE_STORAGE_BUCKET` (optional)
- `VITE_FIREBASE_MESSAGING_SENDER_ID` (optional)
- `VITE_FIREBASE_MEASUREMENT_ID` (optional)

Also add Vercel domains to Firebase Authorized Domains before go-live.

## Render Plan (API + Runtime Services)

Create three services from this repo:

1. API (Web Service)
2. Scheduler (Background Worker)
3. Worker (Background Worker)

Root directory for all: `apps/api`

Build command:

```bash
pip install -e ../../core -e ../../agent && pip install -r requirements.txt
```

Start commands:

```bash
# API
uvicorn app.main:app --host 0.0.0.0 --port $PORT

# Scheduler
python -m app.runtime.scheduler_service

# Worker
python -m app.runtime.worker_service
```

### Render Env Matrix

Common (`api`, `scheduler`, `worker`):
- `ENV=production`
- `DATABASE_URL=<render-postgres-url>`
- `RUNTIME_MODE=external`
- `MAX_WORKITEM_CONCURRENCY=3`

GitHub app/runtime auth:
- `api` requires:
  - `GITHUB_APP_ID`
  - `GITHUB_PRIVATE_KEY`
  - `RUNTIME_GIT_AUTH_MODE=github_app_https`
- `worker` should also get the same GitHub values when deployed as separate worker service.
- `scheduler` does not require GitHub app secrets.
- Optional/recommended:
  - `GITHUB_WEBHOOK_SECRET`

## Local Testing Checklist (Before Cloud Rollout)

- Landing page + auth flow works locally.
- Project creation works.
- Environment Center loads and actions respond.
- Mission Control deployment governance surfaces render.
- Deployment readiness contract endpoint is healthy.
- Runtime flow works in external mode with scheduler + worker running.
- Build passes:

```bash
npm --prefix apps/web run build
```

## Rollout Gate (When You Decide to Deploy)

Deploy only after:

1. 10+ successful local end-to-end runs.
2. No blocking auth or environment sync issues.
3. Required secrets inventory is complete.
4. Smoke test plan for Vercel + Render is written and ready.

