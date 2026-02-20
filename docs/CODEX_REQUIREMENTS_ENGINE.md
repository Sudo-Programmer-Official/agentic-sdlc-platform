# Codex Task Pack — Requirements Intelligence + Documentation Engine (B2)
Guiding constraints (inherit from backlog):
- No new external dependencies unless required and approved.
- Keep changes minimal; follow existing patterns (in-memory stores for now).
- Log key actions to the ledger.
- Deterministic stub extractor (will swap to Bedrock later).
- Update docs/tests with each change; provide verification steps.

## Core Models (Source of Truth)

TASK_ID: B2-A1  
GOAL: Add core models for FR/QR + Requirement Graph + Snapshot support.  
SCOPE:
- Extend core models with RequirementType (FR, QR), QualityType (performance, security, reliability, usability, scalability, maintainability, availability, privacy, compliance, cost).
- Add RequirementNode, RequirementEdge, RequirementGraph structures.
- Export via __init__.py.  
ACCEPTANCE_CRITERIA:
- Models serialize/deserialize cleanly (pydantic/dataclass equivalence not required, but types solid).
- Graph holds nodes/edges with metadata (confidence, source, tags, relations, weight).  
FILES_ALLOWED:
- core/src/core/models/models.py
- core/src/core/models/__init__.py  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: B2-A2  
GOAL: Add deterministic snapshot hashing for RequirementGraph.  
SCOPE:
- Implement RequirementGraphSnapshot (project_id, graph_version, sha256, created_at, created_by).
- Deterministic hash: stable ordering of nodes/edges by id.  
ACCEPTANCE_CRITERIA:
- Same graph produces same sha; reordering nodes/edges does not change hash.
- Unit test covers hash stability.  
FILES_ALLOWED:
- core/src/core/models/**
- core/tests/** (if present; otherwise add new)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Services (FastAPI Orchestrator)

TASK_ID: B2-B1  
GOAL: RequirementGraph service (CRUD + approval + staleness).  
SCOPE:
- Create requirements_service.py with in-memory store (pattern-match other services).
- Capabilities: create draft graph, update graph (nodes/edges), approve graph (snapshot + status), mark stale on post-approval edits.
- Ledger events: graph_created, graph_updated (with change summary), graph_approved (with snapshot hash), graph_marked_stale.  
ACCEPTANCE_CRITERIA:
- Graph persists per project in service store.
- Approval locks current version; later edits flip status to STALE and bump version.
- Ledger entries emitted with sufficient detail.  
FILES_ALLOWED:
- apps/api/app/services/requirements_service.py
- apps/api/app/services/__init__.py
- core/src/core/ledger/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: B2-B2  
GOAL: Propagation flags for downstream refresh.  
SCOPE:
- Add boolean flags to project model (architecture_refresh_needed, plan_refresh_needed, test_refresh_needed).
- Rules: QR touched → architecture + plan + tests; FR touched → plan + tests; edges touched → plan.
- Log propagation decisions in ledger.  
ACCEPTANCE_CRITERIA:
- Flags set/reset deterministically based on graph updates.
- Ledger records flag changes.  
FILES_ALLOWED:
- core/src/core/models/**
- apps/api/app/services/requirements_service.py
- core/src/core/ledger/**
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## API (Schemas + Routes)

TASK_ID: B2-C1  
GOAL: Schemas for PRD ingestion, graph fetch/update/approve.  
SCOPE:
- Add Pydantic models for PRD ingestion request, graph response, graph update, approve request/response.  
ACCEPTANCE_CRITERIA:
- Schemas cover fields described in task pack; validation errors are clear.  
FILES_ALLOWED:
- apps/api/app/api/v1/schemas.py  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: B2-C2  
GOAL: Endpoints for requirements lifecycle.  
SCOPE:
- POST /api/v1/projects/{project_id}/prd (store PRD artifact; trigger extraction stub).
- GET /api/v1/projects/{project_id}/requirements-graph
- PUT /api/v1/projects/{project_id}/requirements-graph (update/replace; mark stale if approved).
- POST /api/v1/projects/{project_id}/requirements-graph/approve (returns snapshot hash).  
ACCEPTANCE_CRITERIA:
- Approval locks current version; subsequent PUT marks stale.
- Stale state aligns with existing stale mechanics (409 for downstream operations that require freshness).  
FILES_ALLOWED:
- apps/api/app/api/v1/routes.py
- apps/api/app/api/v1/schemas.py
- apps/api/app/services/requirements_service.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Extraction Engine (Agent Package)

TASK_ID: B2-D1  
GOAL: Deterministic PRD → RequirementGraph extractor stub.  
SCOPE:
- Add agent/runtime/requirements_intelligence.py with extract_graph_from_prd(text: str) -> RequirementGraph.
- Heuristics: lines starting with Must/Should/Allow => FR; keywords (performance, secure, scalable, reliable) => QR; assign FR-001… and QR-001…; confidence 0.9 for strong match else 0.7.  
ACCEPTANCE_CRITERIA:
- Given same text, extractor returns same graph with IDs and edges.
- No external calls; pure function.  
FILES_ALLOWED:
- agent/src/agent/runtime/requirements_intelligence.py
- agent/tests/** (if added)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: B2-D2  
GOAL: Wire extractor into PRD endpoint.  
SCOPE:
- PRD POST endpoint invokes extractor, stores graph draft via requirements_service.  
ACCEPTANCE_CRITERIA:
- Posting PRD returns graph_version/status DRAFT; GET returns extracted graph.  
FILES_ALLOWED:
- apps/api/app/api/v1/routes.py
- apps/api/app/services/requirements_service.py
- agent/src/agent/runtime/requirements_intelligence.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## UI (Vue Mission Control)

TASK_ID: B2-E1  
GOAL: Add project-scoped Requirements page and route.  
SCOPE:
- Sidebar item “Requirements” under project scope.
- Route: /projects/:projectId/requirements.  
ACCEPTANCE_CRITERIA:
- Sidebar item enabled only when project selected; route renders page.  
FILES_ALLOWED:
- apps/web/src/router/**
- apps/web/src/App.vue
- apps/web/src/views/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: B2-E2  
GOAL: Requirements editor UI (PRD submit, FR/QR edit, edges, approve).  
SCOPE:
- View/component with: PRD textarea + submit; FR list editable; QR list editable with quality_type dropdown; edge table add/remove; relation dropdown; buttons: Save Draft, Approve Graph, Run AI Improve (stub showing “coming next”).
- Status badges: DRAFT / APPROVED / STALE.
- Approve shows snapshot hash.  
ACCEPTANCE_CRITERIA:
- User can edit FR/QR text and quality types; add/remove edges; save and see updates.
- Approve locks current version (UI disables edits or warns) until next change marks stale.
- “Run AI Improve” shows stub toast.  
FILES_ALLOWED:
- apps/web/src/views/Requirements.vue
- apps/web/src/components/** (if split)
- apps/web/src/state/**
- apps/web/src/api/** (if added)  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (component/unit where feasible)  
OUTPUT:
- PR-ready changes + verification steps

TASK_ID: B2-E3  
GOAL: Surface propagation flags in UI.  
SCOPE:
- Show architecture/plan/test refresh flags on Requirements page (and/or Project Overview).  
ACCEPTANCE_CRITERIA:
- Flags reflect API values; empty/false state is clear.  
FILES_ALLOWED:
- apps/web/src/views/**
- apps/web/src/components/**
- apps/web/src/state/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Governance Integration

TASK_ID: B2-F1  
GOAL: Gate stage transitions on requirements graph approval/freshness.  
SCOPE:
- REQUIREMENTS_DRAFTED → REQUIREMENTS_APPROVED requires graph status APPROVED.
- Starting DESIGN_DRAFTED requires graph not stale; if stale return 409 “Requirements graph changed since approval.”
- Ledger logs gating decisions.  
ACCEPTANCE_CRITERIA:
- Transitions blocked when graph missing/ stale; allowed when approved and fresh.
- Ledger contains gate results.  
FILES_ALLOWED:
- core/src/core/sdlc/**
- apps/api/app/services/**
- apps/api/app/api/v1/routes.py
- apps/api/tests/**  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Tests (API)

TASK_ID: B2-G1  
GOAL: End-to-end API test for requirements graph flow.  
SCOPE:
- Test steps: create project → POST PRD → GET graph (nodes/edges exist) → PUT update node text → approve graph → update after approval -> graph becomes stale → attempt stage advance/run start returns 409.  
ACCEPTANCE_CRITERIA:
- Test passes and covers stale/approval gating behaviors.  
FILES_ALLOWED:
- apps/api/tests/test_requirements_graph.py
- fixtures/helpers as needed.  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests  
OUTPUT:
- PR-ready changes + verification steps

## Docs

TASK_ID: B2-H1  
GOAL: Document “Requirements Intelligence Engine” in ARCHITECTURE.md.  
SCOPE:
- Describe data flow: PRD ingestion → extraction stub → graph edit/approve → propagation flags → stage gating → UI surfaces.
- Note future Bedrock/AI improvements.  
ACCEPTANCE_CRITERIA:
- Section present; links endpoints and UI page; clear next steps for AI swap.  
FILES_ALLOWED:
- docs/ARCHITECTURE.md  
CONSTRAINTS:
- no new deps unless approved
- keep changes minimal
- add tests (n/a; proofread)  
OUTPUT:
- PR-ready changes + verification steps
