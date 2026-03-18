# Run Console Product Spec

See also: `docs/agent-runtime-vision-roadmap.md`, `docs/human-in-the-loop-runtime-roadmap.md`, `docs/runtime-foundation-spec.md`, `docs/network-and-recovery-architecture.md`, and `docs/software-execution-cockpit-blueprint.md`. This document narrows those roadmaps into a concrete product and engineering spec for the visible execution experience in Mission Control.

## Objective

Build Mission Control into an observable, steerable software execution system rather than a black-box AI task launcher.

The user should be able to:

1. submit a task in natural language
2. see what the system understood and plans to do
3. watch the environment, commands, and verification steps live
4. intervene when the run is drifting
5. understand what passed, failed, or is still waiting
6. finish with reviewable artifacts such as diffs, commits, pull requests, logs, and traces

## Product Thesis

The premium experience is not "AI wrote code."

It is:

- the machine thinks visibly
- the machine acts visibly
- the machine validates visibly
- the machine fails honestly
- the user can steer without restarting

That is the trust loop the product must optimize for.

## Core Principles

### 1. Visible by default

Every meaningful run must expose:

- current goal
- current hypothesis
- files explored
- commands executed
- environment context
- validation status
- blocking reason
- next suggested action

### 2. Human-readable first

Mission Control should describe actions as operator-readable events first, with technical detail available on demand.

Example:

- "Opened `DashboardView.vue` to inspect safe-area layout handling"
- "Running frontend build"
- "Workspace clone blocked because GitHub App credentials are missing"

### 3. Environment-aware execution

The system must know which runtime and platform it is acting against before it changes code or runs validation.

### 4. Progressive verification

The runtime should run the smallest useful proof after each meaningful change instead of guessing that a change worked.

### 5. Steering is first-class

Users must be able to pause, redirect, narrow scope, retry, skip, or require approval without discarding the whole run.

## Product Surfaces

### A. Run Console

Primary live panel for the active run.

It should show:

- run goal
- current step
- current executor
- current hypothesis
- active command
- recent command output
- latest failure
- next suggested step
- artifact and branch status

This is the command center for the run.

### B. Action Timeline

Every agent action becomes an event.

Examples:

- searched for `Notification`
- opened `DashboardView.vue`
- detected browser-only API access on native shell
- patched native guard
- ran `npm run build`
- build passed
- waiting for mobile sync

Each event should include:

- timestamp
- actor or executor
- event type
- short summary
- status
- optional technical payload

### C. Environment Inspector

This shows the execution context explicitly.

It should surface:

- project
- repo
- branch
- commit SHA
- dirty state
- runtime target
- environment name
- API base URLs
- connected services
- required secret names
- available secret names
- missing secret names
- platform capability snapshot
- workspace location

Secret names and presence should be visible. Secret values must never be shown.

### D. Validation Matrix

This is the proof layer for the run.

Rows should include:

- format
- typecheck
- lint
- targeted tests
- build
- smoke test
- preview deploy
- manual verification

Each row should show:

- status
- scope
- command used
- duration
- failure summary
- rerun availability

### E. Steering Layer

The user must be able to intervene mid-flight.

Required controls:

- pause run
- resume run
- retry step
- retry validation only
- skip optional step
- show diff before apply
- narrow scope
- redirect run with new instruction
- require approval before mutation
- revert last patch

## Environment Context Model

Every run should construct a visible environment context object before execution begins.

Suggested shape:

```json
{
  "project_id": "uuid",
  "run_id": "uuid",
  "repo_full_name": "org/repo",
  "branch_name": "run/abc123",
  "commit_sha": "abc123",
  "runtime_target": "api_embedded",
  "environment_name": "staging",
  "frontend_base_url": "https://web.example.com",
  "backend_base_url": "https://api.example.com",
  "required_secrets": ["DATABASE_URL", "OPENAI_API_KEY", "GITHUB_APP_ID", "GITHUB_PRIVATE_KEY"],
  "available_secrets": ["DATABASE_URL", "OPENAI_API_KEY", "GITHUB_APP_ID"],
  "missing_secrets": ["GITHUB_PRIVATE_KEY"],
  "platform": {
    "surface": "capacitor_ios",
    "notification_api": false,
    "service_worker": false,
    "native_push_bridge": true
  },
  "workspace": {
    "workspace_root": "/tmp/workspaces/...",
    "repo_path": "/tmp/workspaces/.../repo",
    "logs_path": "/tmp/workspaces/.../logs"
  }
}
```

## Step and Action Contracts

### Step Contract

Every work item or run step should emit:

- `step_id`
- `name`
- `type`
- `executor`
- `status`
- `started_at`
- `finished_at`
- `input_summary`
- `output_summary`
- `error_summary`
- `can_skip`
- `can_retry`
- `requires_user_input`

### Action Contract

Every low-level action should emit:

- `action_id`
- `step_id`
- `kind`
- `status`
- `summary`
- `started_at`
- `finished_at`
- `artifact_refs`
- `details`

Important action kinds:

- `SEARCH`
- `OPEN_FILE`
- `EDIT_FILE`
- `DELETE_FILE`
- `RUN_COMMAND`
- `GENERATE_PATCH`
- `APPLY_PATCH`
- `BUILD`
- `TEST`
- `LINT`
- `DEPLOY_PREVIEW`
- `WAITING_FOR_APPROVAL`

## Backend Architecture

### 1. Run Envelope

Every user-triggered task should create a durable run envelope that holds:

- normalized goal
- planning outputs
- environment context
- current stage
- blocking reason
- intervention history
- validation state

### 2. Event Stream

Persist ordered product events, not only system logs.

Minimum event types:

- `RUN_CREATED`
- `RUN_PARSED`
- `RUN_PLANNED`
- `ENVIRONMENT_RESOLVED`
- `WORKSPACE_PREPARE_STARTED`
- `WORKSPACE_PREPARED`
- `COMMAND_STARTED`
- `COMMAND_COMPLETED`
- `PATCH_GENERATED`
- `PATCH_APPLIED`
- `VALIDATION_STARTED`
- `VALIDATION_COMPLETED`
- `RUN_BLOCKED`
- `RUN_AWAITING_APPROVAL`
- `RUN_RESUMED`
- `RUN_COMPLETED`
- `RUN_FAILED`
- `UI_RECONCILIATION_PENDING`
- `UI_RECONCILIATION_RESOLVED`

### 3. Environment Inspection Service

Add a backend service that resolves and snapshots:

- runtime mode
- provider auth mode
- repo status
- env variable presence
- deployment target
- capability flags
- service endpoints

This snapshot should be persisted at run bootstrap and refreshed when material context changes.

### 4. Validation Service

The runtime should schedule verification progressively:

#### Level 1: fast checks

- syntax
- typecheck
- lint

#### Level 2: scoped checks

- tests related to changed files
- targeted route or feature checks
- single-service build

#### Level 3: confidence checks

- full build
- preview launch
- smoke path
- screenshot or response checks

#### Level 4: release checks

- broader test suite
- deploy gate
- rollback readiness

The service should record exactly:

- what changed
- what was run
- why that validation scope was chosen
- what result came back

### 5. Intervention Handler

Provide explicit runtime control APIs:

- `pause_run(run_id)`
- `resume_run(run_id)`
- `retry_step(run_id, step_id)`
- `retry_validation(run_id, validation_id)`
- `skip_step(run_id, step_id)`
- `override_step_input(run_id, step_id, patch)`
- `redirect_run(run_id, instruction)`
- `revert_last_patch(run_id)`
- `cancel_run(run_id)`

## Frontend Architecture

### Mission Control Layout

Mission Control should be composed of these stacked surfaces:

1. run summary rail
2. execution timeline
3. run console
4. environment inspector
5. validation matrix
6. review surface
7. intervention bar
8. operator console

### Key Components

- `RunConsolePanel`
- `StepTimeline`
- `EnvironmentInspectorPanel`
- `ValidationMatrixPanel`
- `InterventionBar`
- `RecoveryBanner`
- `DebugDetailsDrawer`

### Frontend State

Suggested store fields:

- `activeRun`
- `activeEnvironment`
- `activeStep`
- `runEvents`
- `commandFeed`
- `validationChecks`
- `blockingReason`
- `uiSyncStatus`
- `overrideDraft`

## Current Baseline and Gap

### Already in place

The repo now has the beginnings of this experience:

- durable runs and work items
- Mission Control timeline
- execution console API
- live workspace and command audit panel
- review surface
- operator console

### Missing next

The next major gaps are:

- explicit environment inspector instead of only workspace metadata
- validation matrix with stable step rows
- intervention API and UI controls
- platform capability snapshot
- backend success vs UI reconciliation state split
- memory of repeated correction patterns

## Phase Plan

### Phase 1: Run Console

Ship:

- current goal
- current step
- active command
- command output tail
- files changed summary
- latest failure
- next suggested step

Exit criteria:

- user can answer "what is it doing right now?"

### Phase 2: Environment Inspector

Ship:

- runtime target
- env mode
- base URLs
- secret presence
- missing requirements
- repo branch and commit
- platform capability snapshot

Exit criteria:

- environment and runtime misconfiguration is visible without opening infra logs

### Phase 3: Validation Matrix

Ship:

- build, lint, typecheck, tests, smoke rows
- status, duration, scope, and rerun actions
- blocking verification surfaced clearly

Exit criteria:

- user can answer "what did it prove?"

### Phase 4: Steering Controls

Ship:

- pause
- resume
- retry step
- narrow scope
- show diff before apply
- skip optional step
- redirect instruction

Exit criteria:

- user can redirect a drifting run in under 10 seconds

### Phase 5: Pattern Memory

Ship:

- recurring failure fingerprints
- known-fix suggestions
- automatic capability guard suggestions
- operator hints from similar historical incidents

Exit criteria:

- repeated failure classes become faster to diagnose and recover

## Acceptance Criteria

For a healthy run, Mission Control should make all of the following visible without requiring backend logs:

- what the run is trying to do
- which files or areas it inspected
- which command is active
- what environment it is targeting
- which secrets or capabilities are missing
- what validation ran
- why the run is blocked, if blocked
- what action the operator can take next

## Product Sentence

We are building an observable, steerable software execution system, not just an AI coder.
