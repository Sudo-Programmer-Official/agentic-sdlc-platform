# API Service

FastAPI-based orchestration layer for SDLC state management, approvals, and agent execution.
This service exposes versioned REST endpoints and hosts configuration, routing, and startup.

## Local Development
Install shared packages first:

```
pip install -e core
pip install -e agent
```

To bring up the local stack together from the repo root:

```bash
./scripts/dev_stack.sh
```

This starts the API, scheduler, worker, and web app, and writes logs under `.dev-stack/`.

## Architecture Guardrails

The production architecture is intentionally split so the runtime stays deterministic:

- execution vs intelligence plane: [`docs/architecture/execution-intelligence-plane.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/execution-intelligence-plane.md)
- production agent design rules: [`docs/architecture/production-agent-design-principles.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/production-agent-design-principles.md)
- architecture scorecard: [`docs/architecture/ai-engineering-agent-scorecard.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/ai-engineering-agent-scorecard.md)
- blueprint gap analysis: [`docs/architecture/industry-blueprint-gap.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/industry-blueprint-gap.md)
- stabilization gate: [`docs/architecture/stabilization-checklist.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/stabilization-checklist.md)
- continuous repo understanding v1: [`docs/architecture/continuous-repo-understanding-v1.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/continuous-repo-understanding-v1.md)
- runtime execution graph spec: [`docs/architecture/runtime-execution-graph-spec.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/runtime-execution-graph-spec.md)

The import guard for this boundary lives in:

- [`apps/api/tests/test_execution_plane_imports.py`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/apps/api/tests/test_execution_plane_imports.py)

Backend is running via Docker now.

From the repo root, the backend command is:

```bash
docker compose up -d --build db api scheduler worker
```

I verified the stack is up and `http://localhost:8000/health` returns `{"status":"ok"}`. Postgres is exposed on `localhost:5432`, and the running backend services are `db`, `api`, `scheduler`, and `worker`.

Use these commands going forward:

```bash
docker compose ps
docker compose logs -f api scheduler worker db
docker compose down
```

One important detail: Compose uses the repo-root [`.env`](Documents/sudo-programmer-official/agentic-sdlc-platform/.env), not `apps/api/.env`. For Docker local startup, the current root `.env` is already set up correctly to use the `db` container.

## Runtime Mode Profiles

Use mode profiles when you want to switch between high-throughput execution and strict runtime gating.

- `apps/api/.env.fast`: Looser runtime gates, faster autonomous flow.
- `apps/api/.env.strict`: Tighter runtime gates, explicit confirmations.

Switch mode from repo root:

```bash
./scripts/switch-runtime-mode.sh fast
./scripts/switch-runtime-mode.sh strict
```

After switching, restart API, scheduler, and worker so the new values are loaded.
