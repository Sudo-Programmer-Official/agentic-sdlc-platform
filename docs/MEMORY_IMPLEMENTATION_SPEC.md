# Memory Implementation Spec

## Purpose

Translate `CONTINUOUS_ENGINEERING_MEMORY.md` into concrete implementation steps against the current codebase.

Scope:

- backend data model additions
- API surfaces
- Mission Control and Project Overview UX changes
- rollout order for next 2 sprints

## Current Baseline (Already Implemented)

Implemented foundations:

- run replay timeline (`run_events` + artifacts + statuses)
- run summary materialization (`run_summaries`)
- requirement intelligence scoring and compression (`requirement_memories`)
- recovery memory learning (`recovery_memory_profiles`)
- requirement tracking + requirement timeline UI
- knowledge change/event/proposal pipeline

Reference services:

- `apps/api/app/services/run_timeline.py`
- `apps/api/app/services/run_summary_builder.py`
- `apps/api/app/services/requirement_memory.py`
- `apps/api/app/services/requirement_intelligence.py`
- `apps/api/app/runtime/runtime_recovery_service.py`
- `apps/api/app/services/knowledge_service.py`

## Target Capabilities (Gap Closure)

1. Unified `Project Evolution Timeline` (cross-domain event stream)
2. Standardized summary artifacts for run, requirement, recovery, deployment, architecture
3. Requirement health longitudinal intelligence (trend-aware, not snapshot-only)
4. Deployment intelligence memory (correlated failure patterns and rollout risk hints)
5. Architecture impact inference from historical change/failure correlations

## Data Model Deltas

### 1) Add Summary Artifact Registry

Create table `memory_summary_artifacts`:

- `id` UUID PK
- `tenant_id`, `project_id`
- `summary_type` (`run`, `requirement`, `recovery`, `deployment`, `architecture`, `project_evolution`)
- `source_entity_type` (`run`, `requirement`, `project`, `deployment`, `architecture_profile`)
- `source_entity_id` (string UUID/ref)
- `version` int
- `window_start_at`, `window_end_at`
- `payload` JSONB
- `quality_score` float nullable
- `created_at`, `updated_at`

Indexes:

- `(project_id, summary_type, created_at desc)`
- `(source_entity_type, source_entity_id, version desc)`

### 2) Add Unified Timeline Store

Create table `project_evolution_events`:

- `id` UUID PK
- `tenant_id`, `project_id`
- `event_at` timestamp
- `event_type` (normalized enum-like string)
- `domain` (`requirement`, `run`, `recovery`, `deployment`, `architecture`, `contract`, `knowledge`)
- `title`, `summary`
- `severity` (`info`, `warning`, `critical`)
- `status` (`open`, `resolved`, `superseded`, `observed`)
- `requirement_id` nullable
- `run_id` nullable UUID
- `work_item_id` nullable UUID
- `deployment_ref` nullable string
- `related_artifact_ids` JSONB array
- `related_file_paths` JSONB array
- `metadata` JSONB
- `created_at`

Indexes:

- `(project_id, event_at desc)`
- `(project_id, domain, event_at desc)`
- `(project_id, requirement_id, event_at desc)`
- `(project_id, run_id, event_at desc)`

### 3) Add Requirement Health History

Create table `requirement_health_snapshots`:

- `id` UUID PK
- `tenant_id`, `project_id`
- `requirement_id`
- `health_score`, `stability_score`, `risk_level`
- `retry_count`, `regression_count`, `unresolved_count`
- `validation_coverage_score` nullable
- `volatility_score` nullable
- `stale` bool
- `snapshot_payload` JSONB
- `captured_at`

Indexes:

- `(project_id, requirement_id, captured_at desc)`

## Backend Service Deltas

### A) Timeline Aggregator Service

Add `apps/api/app/services/project_evolution_timeline.py`:

- consume existing signals from runs/events/recovery/knowledge/contracts
- normalize to `project_evolution_events`
- expose filtering and pagination
- maintain deterministic ordering: `(event_at desc, id desc)`

Event mapping examples:

- `RUN_CREATED` -> `domain=run`
- `WORK_ITEM_RECOVERY` -> `domain=recovery`
- contract violation records from run summaries -> `domain=contract`
- requirement graph approval/update -> `domain=requirement`
- deployment/push/PR events -> `domain=deployment`

### B) Summary Artifact Builder

Add `apps/api/app/services/memory_summary_builder.py`:

- create/update summary artifacts after run completion
- build `project_evolution` summary windows (e.g., last 24h, 7d)
- emit quality/confidence fields for downstream ranking

Integrate hooks in:

- run completion path (`run_service` / orchestration completion)
- requirement update/approval path (`requirements_service`)
- recovery terminal events (`runtime_recovery_service`)

### C) Requirement Health Trend Service

Add `apps/api/app/services/requirement_health_history.py`:

- persist periodic snapshots from current intelligence function
- compute trends: improving, degrading, volatile, stale
- detect repeated regressions in rolling window

## API Deltas

Add endpoints in `apps/api/app/api/v1/mission_control.py`:

- `GET /projects/{project_id}/memory/timeline`
- `GET /projects/{project_id}/memory/timeline/summary`
- `GET /projects/{project_id}/memory/summary-artifacts`
- `GET /projects/{project_id}/requirements/{requirement_id}/health-history`

Query support for timeline endpoint:

- `domain`
- `requirement_id`
- `run_id`
- `severity`
- `event_type`
- `from`, `to`
- `cursor`, `limit`

Add schemas in `apps/api/app/schemas/mission_control.py` or new `schemas/memory_timeline.py`.

## UI Deltas

### 1) Mission Control: Project Evolution Timeline Panel

Primary location: `apps/web/src/views/MissionControl.vue`

Add:

- cross-domain timeline stream
- filter chips (domain/severity/requirement/run)
- “Replay Point” action per event (jump to run timeline or requirement timeline)

### 2) Project Overview: Memory Health Card

Location: `apps/web/src/views/ProjectOverview.vue`

Add cards:

- memory coverage score (percentage of runs with summary artifacts)
- top degrading requirements
- top recurring recovery signatures
- deployment risk hints (if available)

### 3) Requirements View: Health Trend Visualization

Location: `apps/web/src/views/Requirements.vue`

Add:

- sparkline/trend label for health over time
- volatility badge
- regression streak indicator

## Rollout Plan (2 Sprints)

## Sprint 1 (Foundation Unification)

Deliver:

1. `project_evolution_events` table + ingest pipeline
2. timeline API (`/memory/timeline`)
3. Mission Control timeline read-only view
4. run/recovery summary artifact records in `memory_summary_artifacts`

Acceptance:

- For a completed run with at least one recovery, timeline shows linked requirement/run/recovery events in one stream.
- Timeline query responds in under 300ms p95 for last 30 days on medium projects.

## Sprint 2 (Intelligence Layer)

Deliver:

1. `requirement_health_snapshots` table + trend computation
2. deployment summary artifact generation
3. architecture summary artifact generation
4. Project Overview memory health cards + Requirements trend UI

Acceptance:

- Requirement detail exposes trend state (`improving`/`degrading`/`volatile`/`stale`).
- Deployment summary can explain top 3 correlated failure patterns for last N runs.

## Observability and Reliability

Add metrics:

- timeline ingestion lag
- summary generation lag
- summary generation failure rate
- timeline query latency (p50/p95/p99)
- snapshot coverage ratio

Add guardrails:

- idempotent upserts for timeline and summaries
- backfill job with checkpoint cursor
- bounded payload size for summary artifacts

## Backfill Strategy

Backfill order:

1. run summaries -> timeline events
2. recovery attempts -> recovery timeline events
3. requirement intelligence snapshots (rolling last N runs per requirement)

Backfill should be resumable and tenant-scoped.

## Risks and Mitigations

Risk: event volume growth and query degradation  
Mitigation: partition/index strategy + summary windows + cursor pagination

Risk: inconsistent linking across requirement/run/work item IDs  
Mitigation: lineage normalization utility and integrity checks during ingest

Risk: duplicate events from retries/replays  
Mitigation: deterministic dedupe key (`project_id + domain + event_type + source_ref + event_at_bucket`)

## Definition of Done

Done means:

- unified timeline live in Mission Control
- summary artifacts generated automatically for run/requirement/recovery/deployment/architecture
- requirement health trends persisted and visible
- operators can answer:
  - what changed?
  - why?
  - from which requirement?
  - through which run?
  - after which failures/recoveries?
  - validated/deployed how?

