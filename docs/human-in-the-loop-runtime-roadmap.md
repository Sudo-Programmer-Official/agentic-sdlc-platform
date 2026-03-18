# Human-in-the-Loop Runtime Roadmap

See also: `docs/run-console-product-spec.md`. This companion spec turns the roadmap into a concrete Mission Control product surface plan for the Run Console, Environment Inspector, Validation Matrix, and steering controls.

## Goal

Design the product so a user can:

- submit a task in natural language
- watch the system interpret and execute it step by step
- intervene mid-flight when the system is drifting
- correct direction without restarting everything
- see clear state, reasoning summary, and next actions

This is the missing layer between a black-box agent and a trustworthy product.

## Core Product Principle

The system should behave like a visible co-pilot, not an invisible automaton.

Every meaningful run should expose:

- what the system understood
- what it is about to do
- what it already did
- what it is unsure about
- where the user can interrupt or edit

## Problem

The current failure pattern is familiar:

- the user gives a task
- backend work may partially succeed
- the UI can hang or look stuck
- the real root cause becomes visible only after logs or extra instrumentation
- the user cannot steer the flow in real time

This creates three trust problems:

1. Opacity: the user cannot tell whether the system is thinking, waiting, stuck, or failed.
2. No intervention point: the user notices drift but cannot guide the system cleanly.
3. Weak recovery UX: even when backend succeeds, frontend state can remain stale and the task feels failed.

## Product Vision

A task should feel like a live mission panel.

The desired experience is:

1. The user speaks or types a task.
2. The system shows parsed intent immediately.
3. The system displays a proposed action plan before or during execution.
4. The user can approve, edit, skip, or redirect any major step.
5. The system streams progress as events.
6. If a step stalls, the UI shows where and why.
7. If the backend finished but the UI is stale, reconciliation recovers state.
8. The user can jump in with corrections such as:
   - "No, not that page"
   - "Use dinner at 8 instead"
   - "Skip this step"
   - "Continue from here"

## Mental Model

Every run should be treated as a state machine with visible checkpoints.

Suggested high-level states:

- `DRAFTED`
- `PARSED`
- `PLANNED`
- `AWAITING_APPROVAL`
- `EXECUTING`
- `NEEDS_INPUT`
- `RECOVERING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

User-visible rule:

The UI should never show only a spinner when the system knows a more specific state.

## UX Architecture

### 1. Task Submission Layer

The system should immediately surface:

- raw input
- normalized interpretation
- extracted entities
- detected schedule or time
- detected goal type
- confidence

Example:

- User: "Go to gym in 1 hr"
- System:
  - Intent: create task
  - Title: Go to gym
  - Time: today, one hour from now
  - Category: health
  - Reminder: yes
  - Confidence: high

This is the earliest drift checkpoint.

### 2. Plan Preview Layer

Before taking meaningful action, show a compact step plan.

Example:

1. Create task record
2. Infer category
3. Extract reminder time
4. Save reminder
5. Refresh dashboard state

User controls:

- approve all
- edit step
- skip step
- cancel run
- add instruction

Low-risk actions can auto-run, but the plan must remain inspectable.

### 3. Live Execution Timeline

The product should show event streaming, not static loading.

Each event should include:

- timestamp
- stage name
- status
- short human-readable summary
- technical details toggle
- retry status when applicable

This makes backend success plus UI-sync failure visible instead of hiding it behind a spinner.

### 4. Intervention Layer

The user must be able to interrupt a running flow and reshape it.

Supported actions:

- pause run
- resume run
- edit next step
- edit extracted values
- replace interpretation
- retry from failed step
- skip optional step
- mark wrong direction
- switch mode from auto to guided

This is what makes the system trainable in-session instead of logs-first.

### 5. State Reconciliation Layer

Not all failures are execution failures. Some are sync failures between backend truth and UI state.

Reconciliation checks should answer:

- did the backend action commit?
- did the frontend receive completion state?
- did the store update?
- did the dialog close?
- did optimistic state clear?
- did a fetch retry happen?

The UX should say:

- "Task created on server, final UI refresh is still pending"

with actions such as:

- refresh
- open created task
- retry UI sync

### 6. Explanation Layer

Users should be able to ask:

- what are you doing?
- why did you choose this?
- what failed?
- what do you need from me?

Two explanation levels are useful:

- simple mode for operator comprehension
- debug mode for implementation detail

## Core Runtime Objects

### Run Envelope

Every user task should produce a visible run envelope with fields such as:

- `run_id`
- `user_input`
- `normalized_goal`
- `extracted_entities`
- `current_stage`
- `current_step`
- `status`
- `confidence`
- `blocking_reason`
- `waiting_on`
- `user_override_log`
- `event_stream`
- `final_outcome`

This should become the shared truth source for UI and orchestration.

### Step Contract

Every execution step should emit the same shape:

- `step_id`
- `name`
- `type`
- `status`
- `started_at`
- `finished_at`
- `input_summary`
- `output_summary`
- `error_summary`
- `can_skip`
- `can_retry`
- `requires_user_input`

This removes black-box behavior and gives Mission Control a stable rendering contract.

### Intervention API

Human-in-the-loop requires explicit runtime controls:

- `pause_run(run_id)`
- `resume_run(run_id)`
- `retry_step(run_id, step_id)`
- `skip_step(run_id, step_id)`
- `override_step_input(run_id, step_id, patch)`
- `redirect_run(run_id, instruction)`
- `cancel_run(run_id)`

Without these, operator control is only conceptual.

### Confidence and Risk Layer

Not every decision deserves the same autonomy.

Auto-execute:

- high-confidence parsing
- local UI-only updates
- low-risk task creation

Ask before continuing:

- ambiguous time extraction
- notification or permission prompts
- destructive actions
- external posting or integration writes

Force confirmation:

- payment
- deletion
- irreversible external actions

### Product Event Model

Track product-facing events, not just backend logs:

- `task_submitted`
- `parse_completed`
- `plan_rendered`
- `user_corrected_parse`
- `step_started`
- `step_completed`
- `step_failed`
- `ui_sync_stalled`
- `reconciliation_succeeded`
- `user_resumed_run`
- `user_redirected_run`

This is how the platform learns recurring failure patterns.

## Lessons From The Current Incident

### 1. Black-box loading wastes time

The real issue was not "loading". It was a concrete missing capability behind a generic loading experience.

Design rule:

Any environment-sensitive browser or runtime API must be protected by a capability guard layer.

Examples:

- `Notification`
- `window.speechSynthesis`
- `ServiceWorker`
- `MediaRecorder`
- `clipboard`

### 2. Backend success and frontend completion are different states

Mutation success is not the same as UX success.

Track both:

- action committed
- UI reconciled

### 3. Native and mobile need capability-aware orchestration

Execution planning must include environment facts such as:

- web browser
- mobile web
- Capacitor iOS
- Capacitor Android
- desktop browser

Then prune impossible steps before they run.

## Roadmap

### Phase 1: Make the system visible

Deliver:

- task run envelope
- event timeline UI
- current step and next step display
- simple failure reason panel
- backend success vs UI sync state split

Success metric:

The user can always answer, "What is it doing right now?"

### Phase 2: Add correction points

Deliver:

- pause and resume controls
- edit extracted values
- retry failed step
- skip optional step
- inline instruction box

Success metric:

The user can redirect a mistaken run in under ten seconds.

### Phase 3: Add adaptive execution policy

Deliver:

- confidence scoring
- platform capability detection
- per-step approval policy
- native and web environment pruning

Success metric:

Fewer false starts and fewer avoidable permission or platform crashes.

### Phase 4: Add memory and pattern learning

Deliver:

- recurring issue fingerprinting
- known-fix suggestions
- auto-guard generation for repeated environment bugs
- operator suggestions derived from incidents

Success metric:

Repeated classes of issues are diagnosed faster over time.

## Suggested Technical Architecture

### Frontend

Components:

- `RunConsole`
- `StepTimeline`
- `InterventionBar`
- `RecoveryBanner`
- `DebugDetailsDrawer`

State:

- `activeRun`
- `activeStep`
- `runEvents`
- `blockingReason`
- `uiSyncStatus`
- `userOverrideDraft`

### Backend

Services:

- run orchestrator
- event bus or stream emitter
- intervention handler
- reconciliation service
- capability guard service
- policy engine

Data model additions:

- `runs`
- `run_steps`
- `run_events`
- `run_overrides`
- `run_recoveries`
- `run_capabilities_snapshot`

## Minimal First Implementation

Do not overbuild the first slice.

Start with:

1. `TaskPlannerDialog` submits a task.
2. Backend returns a `run_id`.
3. UI opens a small live run panel.
4. Timeline emits:
   - parsing
   - category detection
   - reminder extraction
   - backend save
   - UI refresh
5. If dashboard refresh stalls, show:
   - backend task saved
   - retry refresh
   - open task directly
6. Add one intervention control:
   - edit interpreted values

That alone will materially improve trust.

## Product Rules

- never hide specific state behind a generic spinner
- separate execution failure from presentation failure
- every autonomous step must be inspectable
- every recoverable failure must offer the next best action
- every platform-sensitive API must be capability-guarded
- every user correction should become reusable product knowledge

## Open Questions

- Should every task create a visible run, or only AI-assisted ones?
- Should low-risk runs auto-complete silently but remain expandable?
- Where should intervention happen: modal, side drawer, or timeline panel?
- Should step streaming use SSE, WebSocket, or polling first?
- Should user corrections affect only the current run or future behavior too?

## Recommended Next Build Order

1. Add a run-state model for `TaskPlannerDialog`.
2. Split backend success from UI reconciliation state.
3. Add a visible timeline in the dashboard or task flow.
4. Add one retry or reconcile action.
5. Add one correction action for parsed task data.
6. Add capability guards for native-only and browser-only APIs.
7. Add repeated-incident pattern memory.

## Bottom Line

The product should stop behaving like:

- input -> spinner -> hope

and start behaving like:

- input -> interpretation -> visible plan -> live progress -> user steering -> recovery -> completion

That is how the system becomes smart, trustworthy, and fast to debug.
