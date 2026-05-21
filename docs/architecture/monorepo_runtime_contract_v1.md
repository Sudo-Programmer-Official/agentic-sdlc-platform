# Monorepo Runtime Contract v1

## Purpose
This contract defines the canonical governed runtime for the Vue + FastAPI fullstack monorepo.

Scope:
- `runtime-templates/fullstack-monorepo/`
- deterministic runtime initialization
- lifecycle state machine and observability
- package/layer/topology-aware mutation boundaries

## Canonical Topology
- Frontend package: `apps/web`
- Backend package: `apps/api`
- Shared packages: `packages/*`

Default architectural posture:
- component-driven frontend evolution
- module-driven backend evolution
- bounded mutation via execution contract + patch guard

## Runtime Lifecycle
Primary states:
1. `CREATED`
2. `TEMPLATE_INSTANTIATED`
3. `REPO_CONNECTED`
4. `CONTRACT_DERIVED`
5. `GOVERNANCE_READY`
6. `PREVIEW_READY`
7. `ACTIVE`

Recovery/terminal states:
- `FAILED`
- `PAUSED`
- `REPAIRING`
- `ARCHIVED`

Required persisted fields:
- `state`
- `updated_at`
- `timeline[]` with `from_state`, `state`, `ts`, `diagnostics`, `error`
- `last_error`
- `retry_count`

## Initialization Contract
Initialization entrypoint:
- `POST /api/v1/projects/{project_id}/initialize-runtime`

Behavior:
- idempotent when state is already `ACTIVE`
- resumable from `FAILED`/`PAUSED` via `REPAIRING`
- disallowed for `ARCHIVED`
- must not mark `PREVIEW_READY` or `ACTIVE` without preview readiness evidence

## Targeting Contract
Runtime targeting must be deterministic and stage-bounded.

Resolution order:
1. explicit scope (`target_files`, `expected_files`, stage payload)
2. intent inference (`frontend`/`backend`/`shared`, feature signal, topology zone)
3. package resolution (`apps/web`, `apps/api`, `packages/*`)
4. safe topology expansion (adjacent component/service/schema neighbors only)
5. stage normalization
6. patch guard enforcement

Required metadata per mutating stage:
- `package_affinity`
- `layer_affinity`
- `topology_zone`

## Frontend Mutation Rules
Allowed pattern:
- component/page/style scoped mutations under `apps/web/src/...`

Rejected pattern:
- oversized monolithic root rewrites
- mutations outside planned package scope

## Backend Mutation Rules
Allowed pattern:
- route/service/repository/schema/capability modules

Rejected pattern:
- oversized entrypoint rewrites (`app.py`, `main.py`, `apps/api/app/main.py`)
- DB logic inside route modules
- route handler logic inside repository modules
- capability resolution outside allowed capability plan
- files outside backend topology planned scope

## Preview Readiness Contract
`PREVIEW_READY` requires:
- repository connected
- resolvable preview profile contract
- actionable diagnostics on failure

No silent success is allowed.

## Content Contract
Content is optional enhancement, not runtime dependency.

Requirements:
- code renders with inline/default text when content binding fails
- editable content constrained to explicitly declared fields
- no aggressive architecture-level DOM rewriting

## Governance and Repair
Runtime governance must enforce:
- package boundaries
- topology boundaries
- layer boundaries
- capability boundaries

Repair behavior:
- deterministic, canonical, bounded
- PR-driven for drift normalization

## Non-Goals for v1
- arbitrary repo shapes
- microservice-first orchestration
- unconstrained autonomous patching

