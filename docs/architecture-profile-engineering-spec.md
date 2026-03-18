# Architecture Profile Engineering Spec

See also: `docs/software-execution-cockpit-implementation-epics.md`, `docs/software-execution-cockpit-blueprint.md`, `docs/run-console-product-spec.md`, and `docs/runtime-foundation-spec.md`. This document turns Epic 1 into a concrete engineering plan for the first Architecture Profile implementation.

## Objective

Implement a durable, project-bound Architecture Profile that gives the runtime a stable understanding of:

- repo layout
- service and package boundaries
- preferred commands and test flows
- safe refactor zones
- do-not-touch zones
- integration surfaces
- release assumptions

The first version should make architecture assumptions queryable and visible before it tries to automate enforcement broadly.

## Why This Exists

Architecture stability is the multiplier for every later system capability.

Without a project-level architecture profile:

- task routing guesses too much
- patch generation drifts across boundaries
- safety policy becomes generic instead of project-aware
- validation scope becomes noisier than needed
- repeated context lives only in chat or operator memory

## V1 Goals

V1 should deliver:

1. a durable architecture profile record per project
2. editable sections for the most important project constraints
3. derived maps the runtime can query quickly
4. Mission Control and Project Overview visibility
5. read-path integration for future Task Router and Safety Engine work

## V1 Non-Goals

V1 should not yet attempt:

- full automatic enforcement of all boundaries
- complex version graphing or branching of profile revisions
- cross-project templates or inheritance
- model arbitration logic
- full policy engine integration

## Existing System Fit

The spec should align with current repo patterns:

- `Project` is already tenant-bound and minimal
- project-bound APIs already exist for:
  - repo connection
  - preview profile
  - repo map
  - Mission Control overview
- repo map and workspace diagnostics already provide useful derived inputs

This means Architecture Profile should be implemented as another project-bound resource, not as a separate subsystem with its own identity model.

## Data Model

### Recommended table

Add a single project-bound table:

- `architecture_profiles`

### Column layout

Suggested schema:

- `id UUID PK`
- `tenant_id UUID NOT NULL`
- `project_id UUID NOT NULL UNIQUE`
- `status VARCHAR(32) NOT NULL DEFAULT 'DRAFT'`
- `source VARCHAR(32) NOT NULL DEFAULT 'MANUAL'`
- `version INTEGER NOT NULL DEFAULT 1`
- `latest_source_run_id UUID NULL`
- `repo_full_name VARCHAR(255) NULL`
- `repo_default_branch VARCHAR(255) NULL`
- `summary TEXT NULL`
- `profile_json JSONB NOT NULL DEFAULT '{}'`
- `derived_json JSONB NOT NULL DEFAULT '{}'`
- `last_derived_at TIMESTAMPTZ NULL`
- `created_by VARCHAR(200) NULL`
- `updated_by VARCHAR(200) NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

### Why one table for v1

One table is enough because:

- the data is project-scoped
- the sections are naturally document-like
- rollout is faster
- query patterns are mostly by project
- change frequency is low compared to runs or events

If the profile becomes heavily versioned later, a separate revisions table can be added without blocking v1.

## Profile Shape

`profile_json` should be a structured document with stable top-level sections.

### Suggested top-level keys

- `repo_layout`
- `boundaries`
- `module_ownership`
- `integrations`
- `commands`
- `validation_recipes`
- `safe_refactor_zones`
- `do_not_touch_zones`
- `conventions`
- `release_flow`
- `environment_assumptions`

### Example payload

```json
{
  "repo_layout": {
    "monorepo": true,
    "packages": [
      {
        "name": "apps/web",
        "kind": "frontend",
        "owned_by": "product-ui"
      },
      {
        "name": "apps/api",
        "kind": "backend",
        "owned_by": "platform-runtime"
      }
    ]
  },
  "boundaries": [
    {
      "from": "apps/web",
      "to": "apps/api",
      "rule": "http_only",
      "notes": "No direct shared runtime imports from frontend into backend."
    }
  ],
  "commands": {
    "frontend_build": "npm -C apps/web run build",
    "api_tests": "python3 -m pytest -q apps/api/tests",
    "lint": "npm -C apps/web run lint"
  },
  "safe_refactor_zones": [
    "apps/web/src/views",
    "apps/web/src/components/workbench"
  ],
  "do_not_touch_zones": [
    "apps/api/app/db/models",
    "infra"
  ],
  "release_flow": {
    "branch_strategy": "run_branch_then_pr",
    "requires_review_before_pr": true
  }
}
```

## Derived Shape

`derived_json` should store read-optimized outputs generated from the editable profile plus repo map signals.

### Suggested derived keys

- `module_ownership_index`
- `path_boundary_index`
- `validation_recipe_index`
- `integration_surface_index`
- `safe_zone_index`
- `protected_zone_index`
- `command_index`
- `summary_cards`

### Purpose

These are for fast reads by:

- Task Router
- Safety Engine
- Mission Control
- operator tools

### Example derived shape

```json
{
  "path_boundary_index": {
    "apps/web": {
      "layer": "frontend",
      "allowed_dependencies": ["packages/ui", "packages/shared-types"]
    },
    "apps/api": {
      "layer": "backend",
      "allowed_dependencies": ["core", "agent"]
    }
  },
  "validation_recipe_index": {
    "frontend": ["frontend_build", "lint"],
    "backend": ["api_tests"]
  },
  "protected_zone_index": {
    "apps/api/app/db/models": {
      "approval_required": true,
      "reason": "Schema and persistence layer"
    }
  }
}
```

## ORM and Schema Design

### ORM model

Add:

- `apps/api/app/db/models/architecture_profile.py`

Suggested fields:

- `tenant_id`
- `project_id`
- `status`
- `source`
- `version`
- `latest_source_run_id`
- `repo_full_name`
- `repo_default_branch`
- `summary`
- `profile_json`
- `derived_json`
- `last_derived_at`
- `created_by`
- `updated_by`

### Pydantic schemas

Add:

- `ArchitectureProfileOut`
- `ArchitectureProfileUpdate`
- `ArchitectureProfileSectionPatch`
- `ArchitectureProfileDeriveRequest`
- `ArchitectureProfileSummaryOut`

## API Surface

Follow the existing project-bound API style.

### Read full profile

- `GET /api/v1/projects/{project_id}/architecture-profile`

Returns:

- full editable profile
- derived fields
- status
- version

### Upsert profile

- `POST /api/v1/projects/{project_id}/architecture-profile`

Behavior:

- create if absent
- replace editable sections if present
- preserve system-managed metadata

### Patch one or more sections

- `PATCH /api/v1/projects/{project_id}/architecture-profile`

Behavior:

- partial update by top-level section
- supports targeted edits from UI

### Recompute derived maps

- `POST /api/v1/projects/{project_id}/architecture-profile/derive`

Behavior:

- regenerate `derived_json`
- optionally pull repo map hints
- update `last_derived_at`

### Read compact summary

- `GET /api/v1/projects/{project_id}/architecture-profile/summary`

Used by:

- Project Overview
- Mission Control side cards
- Task Router launch panel

### Optional future endpoint

- `POST /api/v1/projects/{project_id}/architecture-profile/bootstrap`

This can later create a first draft from repo map, repo connection, preview profile, and prior runs. It should not be part of the initial implementation unless the team wants a faster onboarding path immediately.

## Service Layer

Add a dedicated service:

- `apps/api/app/services/architecture_profile_service.py`

Responsibilities:

- load profile by project and tenant
- upsert editable sections
- compute derived maps
- merge repo map and connected-repo hints
- produce summary cards for UI

### Required helpers

- `get_architecture_profile(...)`
- `upsert_architecture_profile(...)`
- `patch_architecture_profile_sections(...)`
- `derive_architecture_profile(...)`
- `build_architecture_profile_summary(...)`

## Derivation Strategy

The first derivation pass should be deterministic.

### Inputs

- architecture profile sections
- repo map summary
- connected repo metadata
- preview profile metadata

### Outputs

- path ownership index
- safe and protected path lists
- validation recipe lookup by area
- integration lookup by surface

### Rules

- do not use an LLM in the first derivation pass
- prefer explicit user-entered data over inferred data
- mark uncertain derived fields as inferred

## UI Design

### Project Overview

Add an Architecture Profile card and entry point.

Should show:

- profile status
- repo type
- number of defined boundaries
- number of protected zones
- command coverage
- last derived timestamp

### Architecture Profile screen

Suggested sections:

1. Repo Layout
2. Boundaries
3. Commands and Validation
4. Safe Refactor Zones
5. Protected Zones
6. Integrations
7. Release Flow

### Mission Control

Add a compact read-only architecture summary card.

Should show:

- active architecture profile status
- protected zones relevant to current run
- validation recipes relevant to changed areas
- architecture assumptions used by the run

## Runtime Integration Points

V1 should support read-only integration points for later epics.

### Task Router

Should be able to query:

- protected zones
- validation recipes
- boundary hints

### Safety Engine

Should be able to query:

- protected paths
- approval-required areas
- forbidden pattern markers

### Run Console

Should be able to display:

- architecture assumptions used for the current run
- zones touched by the run

## Migration Plan

### Migration 1

Create the `architecture_profiles` table with:

- unique index on `project_id`
- tenant index on `tenant_id`
- composite index on `(tenant_id, project_id)`

### Migration 2

No destructive backfill is required.

Existing projects should simply have no profile until one is created.

### Optional soft backfill

If desired, a follow-up script can create draft profiles using:

- connected repo metadata
- repo map summary
- preview profile

That backfill should be explicitly marked:

- `status = 'DRAFT'`
- `source = 'BOOTSTRAP'`

## Rollout Plan

### Phase 1

Ship:

- ORM model
- migration
- full read and write APIs
- deterministic derive endpoint
- Project Overview summary card

### Phase 2

Ship:

- dedicated Architecture Profile screen
- Mission Control summary card
- runtime read integration in Task Router and Safety Engine

### Phase 3

Ship:

- optional bootstrap generation
- approval policy hooks
- validation recipe enforcement

## Acceptance Criteria

V1 is complete when:

- a project can persist an architecture profile
- the profile can be viewed and edited through the API
- derived maps are generated deterministically
- Project Overview can show profile summary
- Mission Control can show architecture assumptions for the active run
- later runtime services can query protected zones and validation recipes

## Verification Plan

### Backend tests

- model persistence test
- API create, update, patch, and summary tests
- derive service tests
- permission and tenant scoping tests

### Frontend tests

- Architecture Profile summary rendering
- empty-state rendering when no profile exists
- section patching behavior

## Risks

- overdesigning the schema before enough usage data
- mixing editable source data with derived data too tightly
- pushing enforcement before the profile is trustworthy

## Recommendation

Keep v1 narrow:

- one project-bound table
- editable source sections
- deterministic derived indexes
- visible summary in Project Overview and Mission Control

That is enough foundation for Epic 2 without delaying the cockpit roadmap.
