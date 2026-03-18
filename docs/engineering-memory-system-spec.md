# Engineering Memory System Spec

See also: `docs/knowledge-verification-subsystem.md`, `docs/architecture/knowledge-verification-subsystem.md`, `docs/software-execution-cockpit-blueprint.md`, `docs/software-execution-cockpit-implementation-epics.md`, and `docs/run-console-product-spec.md`. This document defines the Engineering Memory System as the layer that turns reviewed project knowledge into reusable execution truth for future runs.

## Objective

Build an Engineering Memory System that lets the platform start from accumulated engineering knowledge instead of starting from zero on every run.

The system should answer four questions before execution begins:

1. what kind of project is this
2. what rules govern it
3. what has gone wrong here before
4. what proof is required before claiming success

## Product Thesis

You do not want the system to guess better.

You want it to know more before it starts guessing.

That means the runtime should not rely only on:

- the current prompt
- the current repo snapshot
- the current model guess

It should also rely on:

- architecture decisions
- execution rules
- environment facts
- incident history
- validation recipes
- preferred patterns
- known bad patterns
- learned team preferences

## Relationship to the Existing Knowledge Subsystem

The repo already has a reviewed knowledge publication system:

- `knowledge_events`
- `knowledge_changes`
- `knowledge_artifacts`
- `knowledge_proposals`
- `knowledge_reviews`
- `knowledge_publications`

That subsystem should remain the canonical review and publication workflow.

The Engineering Memory System should build on top of it rather than replace it.

### Recommended division

The existing knowledge subsystem continues to own:

- ingestion
- proposal generation
- human review
- publication history

The Engineering Memory System adds:

- stricter memory record types
- retrieval-oriented metadata
- runtime context packs
- promotion workflow from observation to rule
- execution-time integration points

In short:

- the knowledge subsystem publishes reviewed memory
- the Engineering Memory System retrieves and applies the right subset at run time

## Design Principles

### 1. Structured first, prose second

Free text is useful, but the runtime needs structured fields for deterministic decisions.

### 2. Retrieval must be narrow

Do not load all memory into every run. Build scoped context packs from the relevant subset.

### 3. Promotion must be staged

Not every observation should immediately become a rule.

### 4. Scope must be explicit

Every memory record needs scope, applicability, source, confidence, and review state.

### 5. Canonical truth must be reviewable

Rules that influence execution should come from reviewed or approved memory, not ad hoc runtime guesses.

## Memory Layers

The system should organize engineering memory in four layers.

### A. Global Engineering Principles

Cross-project principles such as:

- prefer explicit state over hidden spinners
- fail closed on auth
- separate backend success from UI sync success
- checkpoint before retry
- never silently downgrade protected runtime auth

### B. Project-Specific Architecture Profile

Per-project knowledge such as:

- repo layout
- module ownership
- service boundaries
- safe and protected zones
- preferred commands
- deploy topology

### C. Incident and Learning Library

Reusable lessons from real failures such as:

- symptom
- root cause
- affected platform
- fix pattern
- proof used
- prevention rule extracted

### D. Execution-Time Context Pack

A run-scoped bundle loaded just before planning and execution, containing the relevant subset of memory for the current task, platform, and environment.

## Canonical Record Types

The Engineering Memory System should support a small, strict set of record types.

### 1. Decision Record

Used for:

- architecture choices
- preferred patterns
- rejected alternatives
- stable project assumptions

Suggested fields:

- `title`
- `scope`
- `rationale`
- `accepted_pattern`
- `rejected_alternatives`
- `applicable_projects`
- `status`
- `confidence`
- `last_reviewed_at`

### 2. Incident Record

Used for:

- real failures
- root causes
- fix patterns
- proof of repair

Suggested fields:

- `symptom`
- `root_cause`
- `platform`
- `environment`
- `impacted_modules`
- `fix`
- `proof_used`
- `prevention_rule_extracted`
- `severity`
- `confidence`

### 3. Execution Rule

Used for:

- runtime-enforced or runtime-advisory rules

Examples:

- ask before deleting files
- ask before schema changes
- do not retry non-idempotent actions blindly
- infer bounded file scope before escalating mutation risk

Suggested fields:

- `trigger_condition`
- `rule_text`
- `severity`
- `enforcement_mode`
- `review_required`
- `related_validations`

### 4. Environment Rule

Used for:

- platform facts
- capability constraints
- environment-specific fallback strategies

Examples:

- browser Notification is unavailable on Capacitor iOS WebView
- GitHub clone auth requires app id plus private key in the running process
- asyncpg `sslmode` must be normalized

Suggested fields:

- `platform`
- `environment`
- `capability`
- `availability`
- `fallback_strategy`
- `verification_method`

### 5. Validation Recipe

Used for:

- declaring what "done" means for a task class or surface

Examples:

- dashboard task creation requires backend mutation success plus UI reconciliation
- SDLC runtime fix requires clone, patch, tests, artifact persistence, and push proof

Suggested fields:

- `task_class`
- `surface`
- `required_checks`
- `optional_checks`
- `proof_standard`
- `target_environment`
- `manual_review_required`

### 6. Model Observation

Optional but useful for:

- model behavior notes that affect routing or review

Examples:

- planner tends to over-broaden scope on infrastructure issues
- implementer model is strong on small patch generation but weaker on architecture choices

Suggested fields:

- `model_role`
- `observation`
- `impact`
- `recommended_use`
- `confidence`

## Canonical Storage Strategy

### Recommendation

Use the existing knowledge subsystem as the canonical publication layer and add structured memory metadata on top.

### Canonical objects

Continue using:

- `knowledge_artifacts` for published memory items
- `knowledge_proposals` for draft changes
- `knowledge_publications` for version history

### Recommended schema extensions

Extend `knowledge_artifacts` with structured metadata fields such as:

- `artifact_scope`
- `artifact_status`
- `confidence_score`
- `applicability_json`
- `meta_json`
- `review_due_at`
- `expires_at`
- `search_text`

If modifying `knowledge_artifacts` directly is undesirable, create a companion table:

- `engineering_memory_records`

Suggested companion table fields:

- `id UUID PK`
- `artifact_id UUID UNIQUE NOT NULL`
- `tenant_id UUID NOT NULL`
- `project_id UUID NULL`
- `record_type VARCHAR(32) NOT NULL`
- `scope_type VARCHAR(32) NOT NULL`
- `status VARCHAR(32) NOT NULL`
- `confidence_score FLOAT NOT NULL`
- `severity VARCHAR(16) NULL`
- `enforcement_mode VARCHAR(32) NULL`
- `platform VARCHAR(64) NULL`
- `environment VARCHAR(64) NULL`
- `applicability_json JSONB NOT NULL DEFAULT '{}'`
- `meta_json JSONB NOT NULL DEFAULT '{}'`
- `review_due_at TIMESTAMPTZ NULL`
- `expires_at TIMESTAMPTZ NULL`
- `last_used_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

### Preferred v1 path

For v1, the lowest-risk option is:

1. keep published canonical content in `knowledge_artifacts`
2. add `engineering_memory_records` as the retrieval-oriented read model
3. link every memory record to a reviewed artifact

This keeps the existing review subsystem intact while giving the runtime structured retrieval fields.

## Record Status Model

Each learning should move through explicit maturity states.

### Stage 1: Observation

"This happened."

Characteristics:

- low confidence
- not enforced
- often sourced from a run postmortem or incident

### Stage 2: Validated Learning

"This is a repeatable pattern."

Characteristics:

- reviewed by a human or confirmed through repeated evidence
- eligible for retrieval during planning and recovery

### Stage 3: Rule or Recommendation

"The system should use this going forward."

Characteristics:

- may be advisory or enforceable
- can affect routing, approval, validation, or execution behavior

## Applicability Model

Every record should say where it applies.

Suggested applicability fields:

- `global`
- `tenant_ids`
- `project_ids`
- `repository_ids`
- `task_types`
- `modules`
- `platforms`
- `environments`
- `run_stages`
- `tags`

This is what keeps retrieval focused instead of noisy.

## Retrieval Model

The system should build a Context Pack per run rather than loading all memory.

### Inputs to retrieval

- project id
- tenant id
- task type
- risk level
- touched modules
- touched files
- platform
- environment
- current step
- failure class if applicable

### Retrieval order

1. global engineering principles
2. project architecture profile
3. environment and platform rules
4. execution rules relevant to the task
5. similar incidents
6. validation recipes
7. optional model observations

### Retrieval strategy

Use a two-pass approach.

#### Pass 1: deterministic filter

Filter by:

- tenant
- project
- status
- scope
- platform
- environment
- task type
- tags

#### Pass 2: ranking

Rank by:

- explicit match strength
- confidence
- recency if relevant
- severity
- semantic relevance if embeddings exist

### Context pack shape

Suggested runtime payload:

```json
{
  "project_brain": {
    "architecture_profile_id": "uuid",
    "global_principles": [],
    "execution_rules": [],
    "environment_rules": [],
    "similar_incidents": [],
    "validation_recipes": []
  },
  "retrieval_meta": {
    "project_id": "uuid",
    "task_type": "bugfix",
    "platform": "capacitor_ios",
    "environment": "production",
    "selected_record_count": 11
  }
}
```

### Retrieval caps

Keep packs bounded.

Suggested v1 caps:

- global principles: max 5
- execution rules: max 8
- environment rules: max 6
- similar incidents: max 5
- validation recipes: max 4
- model observations: max 3

## Runtime Insertion Points

The Engineering Memory System should influence runs at four points.

### 1. Before planning

Load:

- architecture profile
- environment facts
- relevant execution rules
- prior incidents
- validation recipes

Use it to:

- narrow scope
- avoid known bad paths
- choose safer files
- pick the right verification plan

### 2. During execution

Use memory to:

- block unsafe deletion
- require approval in protected zones
- choose correct auth paths
- avoid unsupported platform APIs

### 3. During failure and recovery

Use memory to:

- match the failure to similar incidents
- propose the safest next step
- select recovery actions and proof requirements

### 4. During verification

Use memory to:

- choose the validation recipe
- require the correct proof standard
- avoid premature "done" claims

## Update Workflow

The memory system needs a deliberate promotion loop.

### Sources of new knowledge

- run postmortems
- operator notes
- successful fix patterns
- failed run reviews
- deployment lessons
- research notes
- repeated incident clusters

### Workflow

1. observation is created from a run, incident, or manual note
2. proposal is generated or submitted
3. reviewer validates, edits, rejects, defers, or approves
4. publication creates or updates the canonical artifact
5. companion retrieval record is created or updated
6. future runs can now retrieve the learning

### Important rule

Not every observation becomes a hard rule.

Promotion to enforceable rule should require:

- explicit human approval
- high confidence
- clear scope
- repeatability or strong proof

## Suggested API Surfaces

The existing knowledge APIs can stay as the review plane. Add engineering-memory reads on top.

### Memory hub reads

- `GET /api/v1/projects/{project_id}/engineering-memory`
- `GET /api/v1/projects/{project_id}/engineering-memory/{record_id}`
- `GET /api/v1/projects/{project_id}/engineering-memory/summary`

### Retrieval

- `POST /api/v1/projects/{project_id}/engineering-memory/context-pack`

Inputs:

- task type
- platform
- environment
- modules
- files
- failure class

Returns:

- bounded context pack with retrieval metadata

### Promotion and maintenance

- `POST /api/v1/projects/{project_id}/engineering-memory/promote`
- `POST /api/v1/projects/{project_id}/engineering-memory/{record_id}/deprecate`
- `POST /api/v1/projects/{project_id}/engineering-memory/{record_id}/revalidate`

The concrete mutation path can still be implemented through the underlying knowledge proposal workflow rather than bypassing review.

## UI Surface

Expose this as an Architecture & Learning Hub within each project.

Suggested sections:

- Architecture Decisions
- Runtime Rules
- Environment Facts
- Known Incidents
- Validation Recipes
- Recent Learnings

Actions:

- save as project rule
- save as reusable fix pattern
- mark as deprecated
- attach to future runs automatically
- review and approve

## Integration with Existing Docs and Systems

### Architecture Profile

Architecture Profile remains the structured project brain for stable design assumptions.

The Engineering Memory System extends it with:

- incidents
- rules
- environment facts
- validation recipes

### Run Console

The Run Console should show which memory was loaded for the run and which rules are currently active.

### Task Router

The Task Router should consume:

- architecture assumptions
- execution rules
- validation recipes
- relevant incidents

### Recovery Engine

The Recovery Engine should consume:

- similar incidents
- environment rules
- previous proven fixes

## Safeguards

### Avoid a dumping ground

Every record must include:

- scope
- confidence
- source
- applicability
- last reviewed date
- optional expiry or review date

### Separate durable from temporary

Examples:

- durable: Notification unavailable in native iOS WebView
- temporary: current production worker revision is missing GitHub App env

Temporary operational issues should not become permanent rules automatically.

### Keep runtime retrieval bounded

The system should prefer a narrow, relevant context pack over a giant memory dump.

## Acceptance Criteria

The Engineering Memory System is useful when:

- the runtime can retrieve relevant project memory before planning
- incident history can inform recovery
- execution rules can influence runtime behavior
- validation recipes can shape proof requirements
- approved learnings become reusable across future runs
- the memory hub is inspectable and editable by humans

## Recommended V1

Start with:

1. structured record types for:
   - decision records
   - incident records
   - execution rules
   - environment rules
   - validation recipes
2. companion retrieval metadata linked to published knowledge artifacts
3. a context-pack endpoint
4. run-time retrieval before planning and verification
5. a project-level Architecture & Learning Hub read surface

That is enough to turn scattered lessons into reusable execution truth without overbuilding the first iteration.
