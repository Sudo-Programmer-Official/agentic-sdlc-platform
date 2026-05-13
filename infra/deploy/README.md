# Deploy

Deployment scripts and infrastructure automation live here.

## Render Blueprint (Vercel + Render + AWS RDS)

For the non-AWS-compute production path, use:

- [render.yaml](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/infra/deploy/render/render.yaml)

This blueprint defines:

- `agentic-sdlc-api` (web service)
- `agentic-sdlc-scheduler` (worker service)
- `agentic-sdlc-worker` (worker service)

End-to-end rollout/runbook:

- [vercel-render-aws-rds.md](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/deployment/vercel-render-aws-rds.md)

## ECS Runtime Env Template

Use [ecs-runtime-container-env.example.json](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/infra/deploy/ecs-runtime-container-env.example.json) as the source-controlled environment contract for ECS task-definition updates.

It defines the expected `environment` and `secrets` blocks for:

- `api`
- `worker`
- `scheduler`

For repo-backed runs, the important rule is:

- `api` and `worker` must both receive `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, and `RUNTIME_GIT_AUTH_MODE=github_app_https`

The scheduler only needs database/runtime settings because it does not clone or mutate repositories.
