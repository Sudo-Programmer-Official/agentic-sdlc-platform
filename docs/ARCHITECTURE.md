# Agentic SDLC – Architecture & Data Model (V1)

## Purpose
A document‑centric, AI‑assisted software factory that keeps every project artifact traceable: Requirements → Design → Tasks → Artifacts → Approvals. This locks in control and auditability while leaving room for automated execution in later phases.

## System Shape
- **Frontend (apps/web)**: Vue + Vite SPA consuming `/api/v1`.
- **Backend (apps/api)**: FastAPI service; will add PostgreSQL for persistence.
- **Infra**: ECS Fargate + ALB; CI/CD auto‑builds and deploys on `main`.

## Domain Model (minimum viable)
### Project
- `id (uuid, pk)`
- `name, description`
- `status` (`INTAKE|PLAN|BUILD|TEST|RELEASE`)
- `created_at, updated_at`

### Document (versioned, typed)
- `id (uuid, pk)`
- `project_id (fk projects)`
- `type` (`requirement|design|plan|test_plan|impl_notes`)
- `version (int, starts at 1, increment per project_id+type)`
- `title`
- `body` (markdown or structured JSON)
- `content_hash` (sha256 of body)
- `created_by`
- `generated_by` (`ai|human`)
- `created_at`
- Unique `(project_id, type, version)`

### Task
- `id (uuid, pk)`
- `project_id (fk projects)`
- `document_id (fk documents)` — source document/version
- `generated_from_document_version (int)`
- `title, description`
- `category` (`func|nonfunc|test|deploy`)
- `stage` (`PLAN|BUILD|TEST`)
- `status` (`PENDING|RUNNING|DONE|FAILED|APPROVED|REJECTED`)
- `assignee`
- `created_at, updated_at`
- Index on `(project_id, status)`

### ActivityLog (audit trail)
- `id (uuid, pk)`
- `project_id (fk projects)`
- `entity_type` (`project|document|task|artifact|trace|approval`)
- `entity_id`
- `action_type` (e.g., `document.created`, `impact.preview`, `tasks.generated`)
- `metadata` (JSONB)
- `actor` (reserved for future auth)
- `created_at`

### Artifact
- `id (uuid, pk)`
- `project_id (fk projects)`
- `task_id (fk tasks)`
- `type` (`code|doc|diagram|log`)
- `uri` (s3/git path)
- `checksum`
- `created_at`

### Approval
- `id (uuid, pk)`
- `project_id (fk projects)`
- `target_type` (`document|task|artifact`)
- `target_id`
- `status` (`PENDING|APPROVED|REJECTED`)
- `decided_by, decided_at, comment`

### Trace (link anything to anything)
- `id (uuid, pk)`
- `from_type`, `from_id`
- `to_type`, `to_id`
- `rationale` (short text)
- Use for Requirement → Task, Task → Artifact, Task → Test Plan, etc.

### (Soon) AgentRun
- `id (uuid, pk)`
- `project_id`
- `input_document_version`
- `status`, `started_at`, `finished_at`
- Links to produced Tasks/Artifacts.

## API Surface (initial)
- `POST /projects` → create project
- `GET /projects/{id}` → fetch project
- `POST /projects/{id}/documents` (type + content) → creates new version
- `GET /projects/{id}/documents?type=requirement` → latest + history
- `POST /projects/{id}/generate-plan` → AI plan → creates Tasks + Traces
- `GET /projects/{id}/tasks` → list/filter
- `POST /tasks/{id}/artifacts` → attach artifact
- `POST /approvals` → generic approval for document/task/artifact
- `POST /projects/{id}/documents/{doc_id}/generate-tasks` → AI-assisted task generation with trace + provenance

## Data Flow (happy path)
1) Create Project.
2) Add Requirements Document (version 1).
3) Call Generate Plan → tasks + traces (Requirement → Task).
4) Execute tasks → attach artifacts; create traces Task → Artifact.
5) Submit approvals (doc/task/artifact) → gated stage movement.

## Persistence & Migration Plan
- Database: **PostgreSQL** (prod), SQLite acceptable for local dev.
- ORM: SQLAlchemy 2.x with Pydantic models for I/O.
- Migrations: Alembic with autogenerate enabled.
- Connection settings via env: `DATABASE_URL` (e.g., `postgresql+psycopg://user:pass@host/db`).

## Security & Audit
- Every write records `created_by` / `generated_by`.
- Approvals are explicit records, not flags on entities.
- Traces make lineage queryable for audits and reporting.

## Why this works
- Document-first: everything starts from controlled documents.
- Traceability: explicit Trace table keeps Requirement → Task → Artifact → Test linked.
- Incremental: V1 delivers persistence + trace; V2 can add agent runs and execution logs without reshaping the core.

## Next Implementation Steps
1) Add DB dependency (`sqlalchemy`, `alembic`, `psycopg[binary]`) to API.
2) Create models + Alembic migrations for tables above.
3) Add DB session dependency in FastAPI.
4) Implement project/document/task endpoints using the new models.
5) Wire UI Workspace to real endpoints (create/open project, list tasks, show document versions and traces).
