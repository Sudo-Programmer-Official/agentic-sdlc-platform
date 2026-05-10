# Production Readiness Execution Plan

## Scope
This document captures the current platform readiness gaps for scaling to thousands of users and defines an execution plan with priorities, concrete changes, and acceptance criteria.

## Audit Date
- May 10, 2026

## Priority Findings

### P0: Tenant isolation gap on summary-style endpoints
- Risk: Cross-tenant data exposure if project IDs are known.
- Evidence:
  - `apps/api/app/api/v1/persistence.py` uses `session.get(Project, project_id)` without tenant scope in:
    - `project_summary`
    - `project_metrics`
    - `plan_history`
- Fix:
  - Require `ctx=Depends(get_tenant_context)` on these endpoints.
  - Query with `Project.id == project_id AND Project.tenant_id == ctx.tenant_id`.
  - Return `404` for non-owned projects.
- Acceptance criteria:
  - Integration tests prove tenant A cannot read tenant B project summary/metrics/history.

### P0: Worker control-plane endpoints lack strong auth/scope
- Risk: Unauthorized registration/claim/heartbeat/complete can mutate runtime state.
- Evidence:
  - Unscoped routes under `apps/api/app/api/v1/persistence.py`:
    - `/agents/register`
    - `/agents/{agent_id}/heartbeat`
    - `/agents`
    - `/agents/{agent_id}/claim`
    - `/work-items/{work_item_id}/complete`
- Fix:
  - Add service-to-service auth (API key or signed token) for worker endpoints.
  - Add tenant/run scoping checks for claimed/completed work items.
  - Restrict these endpoints from public router exposure.
- Acceptance criteria:
  - Unauthorized request returns `401/403`.
  - Worker cannot claim/complete work outside allowed tenant scope.

### P1: Tenancy enforcement disabled by default
- Risk: Unsafe default posture in production.
- Evidence:
  - `tenancy_enforcement: bool = False` in `apps/api/app/core/config.py`.
- Fix:
  - Default to `True` for production profiles.
  - Add startup guard: fail fast in `env=prod` if tenancy enforcement is off.
- Acceptance criteria:
  - Production deployment cannot start with tenancy enforcement disabled.

### P1: Database connection strategy will not scale
- Risk: Connection churn and RDS pressure with `NullPool`.
- Evidence:
  - `apps/api/app/db/session.py` uses `NullPool`.
- Fix:
  - Switch to pooled engine settings for production (`QueuePool` or asyncpg pool defaults with limits).
  - Configure `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`.
  - Add DB saturation dashboards and alerts.
- Acceptance criteria:
  - Load test shows stable p95 latency and no connection exhaustion at target concurrency.

### P1: Polling loops produce avoidable DB load
- Risk: Hot-loop scheduler/worker polling under high run volume.
- Evidence:
  - Scheduler ticks every 1s.
  - Worker loop ticks every 0.5s.
- Fix:
  - Introduce adaptive backoff when no runnable work exists.
  - Trigger worker nudges via event-based signaling where possible.
  - Reduce repeated full scans; prefer narrow indexed queries.
- Acceptance criteria:
  - DB query volume per active run decreases measurably under idle/ramp conditions.

### P1: Vision screenshot payloads are unbounded and persisted inline
- Risk: DB bloat, high memory/IO cost, long request times.
- Evidence:
  - `data_base64` field accepts unbounded string.
  - Full base64 stored in artifact metadata.
- Fix:
  - Enforce request payload size and per-image byte limits.
  - Store binaries in object storage; persist only URI + metadata in DB.
  - Validate content type and image dimensions.
- Acceptance criteria:
  - Oversize payloads rejected with clear `413/400`.
  - No large base64 blobs persisted in DB rows.

### P2: Unpaginated list endpoints
- Risk: Large response payloads and table scans as data grows.
- Evidence:
  - Project/run/event/work-item listing endpoints return full lists.
- Fix:
  - Add cursor or limit/offset pagination.
  - Add stable ordering and indexed filters.
- Acceptance criteria:
  - All list endpoints support pagination and default limits.

### P2: Workspace retention defaults risk disk growth
- Risk: Disk exhaustion over long-lived production uptime.
- Evidence:
  - `workspace_cleanup_policy = "retain"` by default.
- Fix:
  - Use TTL-based cleanup in production.
  - Add periodic workspace GC and observability.
- Acceptance criteria:
  - Workspace usage remains within configured budget during soak tests.

## Execution Plan

## Phase 1 (Security First, 1-2 sprints)
- Owner: Backend Platform
- Deliverables:
  - Tenant-scope fixes for summary/metrics/history endpoints.
  - Worker endpoint authn/authz hardening.
  - Production config guardrails for tenancy enforcement.
- Exit criteria:
  - Security regression tests pass.
  - No cross-tenant read/write found in automated checks.

## Phase 2 (Scale Foundation, 1 sprint)
- Owner: Infra + Backend
- Deliverables:
  - DB pooling config rollout.
  - Polling backoff and query reduction.
  - Baseline performance dashboards.
- Exit criteria:
  - Sustained load tests hit SLO targets without DB saturation.

## Phase 3 (Data + Cost Hardening, 1 sprint)
- Owner: Backend + Infra
- Deliverables:
  - Screenshot upload path moved to object storage.
  - Payload size enforcement.
  - Workspace cleanup policy + GC jobs.
- Exit criteria:
  - DB growth and disk growth slopes are within thresholds.

## Phase 4 (API Ergonomics + Operability, 1 sprint)
- Owner: Backend
- Deliverables:
  - Pagination rollout on all list endpoints.
  - Endpoint-level rate limiting for expensive routes.
  - Runbooks and on-call alerts updated.
- Exit criteria:
  - No unbounded list responses remain in public APIs.

## Suggested Tracking Board
- Epic 1: Tenant + Control Plane Security
- Epic 2: Runtime Throughput and DB Efficiency
- Epic 3: Artifact/Data Path Hardening
- Epic 4: API Pagination and Guardrails

## Verification Checklist (Pre-Prod Gate)
- [ ] Tenant isolation tests pass for all read/write endpoints.
- [ ] Worker APIs reject unauthorized calls.
- [ ] DB pool metrics healthy under projected peak load.
- [ ] Scheduler/worker idle query rates within budget.
- [ ] Screenshot/image ingestion limits enforced.
- [ ] Workspace GC enabled and verified.
- [ ] Pagination enabled on all list endpoints.
- [ ] Alerts and dashboards reviewed by on-call.

