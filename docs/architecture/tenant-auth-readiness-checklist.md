# Tenant Auth Readiness Checklist

## Objective
Introduce tenant-based authentication/authorization (similar to `foundercontent-ai`) without breaking the current happy path:
- create task
- start run
- approve/confirm when needed
- preview
- create PR

## Current happy-path surfaces
- API tenant dependency: `apps/api/app/api/deps.py`
- Mission Control runtime + approvals + PR flow: `apps/web/src/views/MissionControl.vue`
- Global operator approval dialog: `apps/web/src/App.vue`
- Timeline run controls (resume/open approvals): `apps/web/src/views/SdlcTimeline.vue`
- Overview run controls (resume/unblock): `apps/web/src/views/ProjectOverview.vue`
- Client API wrappers: `apps/web/src/api/lifecycle.ts`

## Release gates (must pass)

### Gate 1: Request identity and tenant context
- [x] Every protected API route resolves `TenantContext` from `get_tenant_context`.
- [x] No runtime writes are allowed when tenant resolution fails.
- [x] `ZERO_TENANT` fallback is blocked in enforcement mode for user actions.
- [x] Add explicit error contract for missing/invalid tenant header:
  - status `401/403`
  - stable error code
  - user-facing message for UI.

## Gate 2: Authorization by resource ownership
- [x] Every run/project/artifact query filters by both `project_id` and `tenant_id`.
- [x] Run actions verify tenant ownership before mutate:
  - resume
  - unblock
  - create PR
  - approvals create/update (run-level approval patterns validated; broader approval surface still needs dedicated test).
- [x] Negative tests confirm cross-tenant access is denied.

### Gate 3: Frontend tenant propagation
- [x] Web client sends tenant header consistently in all lifecycle calls.
- [x] No route loads without tenant context after login.
- [x] Tenant switch updates:
  - project picker
  - run list
  - approval queue
  - mission control state.
- [x] Stale run references from prior tenant are cleared.

### Gate 4: Approval/confirmation UX safety
- [x] Keep approval queue and operator confirmation distinct in UI.
- [x] Approval dialogs always reference the run actually requiring action.
- [x] "Go to Exact Run" lands on actionable run and shows available action.
- [x] If no pending action exists, show deterministic "nothing to approve" state.

### Gate 5: Idempotent run operations
- [x] `start`, `resume`, `unblock`, `fork`, `create-pr` are idempotent.
- [x] Double-click/retry on slow network does not create duplicates.
- [x] API returns stable response when action already applied (covered for `resume` conflict stability and repeat `unblock` behavior).

### Gate 6: Preview stability
- [x] UI clearly differentiates stale preview port vs active preview URL.
- [x] "Restart Preview" updates frontend URL in run summary immediately.
- [x] Preview panel includes run id + port + last health check timestamp.

### Gate 7: PR safety and trust signals
- [x] PR dialog shows:
  - changed files
  - additions/deletions
  - concise change summary
  - risk hint.
- [x] Create PR button remains blocked until patch approval is `APPROVED`.
- [x] GitHub permission/connectivity errors are surfaced with remediation text.

### Gate 8: Observability and debugging
- [x] Add correlation id for each operator action from UI -> API -> runtime event.
- [x] Emit events for:
  - action requested
  - action accepted
  - worker picked
  - paused requiring operator
  - resumed
  - completed/failed.
- [x] Add dashboard panel for "stalled run detector":
  - `RUNNING` with no event heartbeat over threshold.

## Test plan (minimum)

### API tests
- [x] tenant missing/invalid -> denied.
- [x] cross-tenant run fetch -> denied.
- [x] cross-tenant resume/unblock/create-pr -> denied.
- [x] same-tenant resume/unblock idempotency -> consistent.

### Frontend tests
- [x] tenant switch clears stale run/approval state.
- [x] approval dialog routes to correct run.
- [x] no false approval alarm when queue empty.
- [x] PR dialog summary rendered from diff metadata.

### E2E smoke tests
- [x] happy path:
  - create task
  - run starts
  - required approval handled
  - preview loads
  - PR created.
- [x] slow network retry path:
  - action retried without duplicate side effects.
- [x] auth failure path:
  - user receives actionable message, no silent stall.

## Rollout strategy
1. Introduce tenant enforcement in `warn` mode with logs only.
2. Run smoke suite and monitor deny metrics for one cycle.
3. Enable strict tenant enforcement for write actions first.
4. Enable strict tenant enforcement for read actions.
5. Keep emergency feature flag to revert to warn mode.

## Definition of done
- [x] All eight gates green.
- [ ] API + FE + E2E suites pass in CI.
- [ ] One full manual happy-flow run passes with tenant auth on.
- [ ] No unresolved "false approval required" issues in Mission Control.

## Current status snapshot (latest)
- Done: core tenant enforcement contract, tenant-scoped ownership checks, cross-tenant denial tests, tenant header propagation, route guard, tenant-switch stale-state cleanup.
- Done: Firebase session bootstrap wiring now sets auth token and tenant context from ID token claims when configured.
- Done: PR review surface coverage, idempotent run action coverage (`start`/`fork`/`create-pr`), workspace-aware request-key propagation, Mission Control stalled-run detector, and auth-failure UX handling.
- Remaining: CI run of API+FE+E2E suites, one manual tenant-auth happy-flow verification run, and final signoff for any residual false-approval alert reports.

## Firebase bootstrap configuration
- Web runtime reads:
  - `VITE_FIREBASE_API_KEY`
  - `VITE_FIREBASE_AUTH_DOMAIN`
  - `VITE_FIREBASE_PROJECT_ID`
  - `VITE_FIREBASE_APP_ID`
- Behavior:
  - If config is missing, bootstrap is a safe no-op.
  - On sign-in/token refresh, client sets:
    - `Authorization: Bearer <id_token>`
    - `X-Tenant-Id` from claims (`tenant_id`, `tenantId`, `https://agentic-sdlc/tenant_id`, `https://foundercontent-ai/tenant_id`).
