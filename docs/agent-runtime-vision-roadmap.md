# Agent Runtime Vision Roadmap

See also: `docs/human-in-the-loop-runtime-roadmap.md`, `docs/run-console-product-spec.md`, `docs/network-and-recovery-architecture.md`, and `docs/software-execution-cockpit-blueprint.md`. These companion documents focus on operator steering, intervention points, UI reconciliation, visible run reasoning, concrete Mission Control surfaces, the lease-safe recovery model, and the higher-level software execution cockpit that sit on top of the durable runtime foundation described here.

## Objective

Build a durable, real-time developer agent platform that behaves like an active software operator. The system should plan, execute, retry, report live progress, and produce real development outcomes such as branches, commits, pull requests, artifacts, and reviewable traces.

This document is the product and engineering reference for evolving the current system from a promising product shell into a resilient execution engine.

## Current Product Direction

The platform is already moving toward the right shape:

- project-centric workflow
- tasks linked to runs
- Mission Control as the live operations surface
- repo connection and runtime execution model
- timeline-based visibility
- worker/runtime concepts
- GitHub-oriented output path

The main shift now is execution durability. A launched run cannot be allowed to silently stall between creation and real work.

## Product Vision

The target experience is a live agent operator for software work.

Users should be able to:

1. select a project
2. choose or create a task
3. launch a run
4. watch the system bootstrap, plan, execute, retry if needed, and update state in real time
5. inspect artifacts, patches, branch changes, pull requests, and validation output
6. refresh or reconnect without losing state
7. resume, replay, compare, or escalate when the run is blocked

The product should feel active and trustworthy, not like a one-shot model call.

## North-Star Principles

### 1. Durable by Default

If a run is accepted, the system must persist enough state to continue even if:

- the request ends
- the browser refreshes
- a worker restarts
- a background coroutine is lost

### 2. State Must Be Explicit

Runs should move through well-defined lifecycle stages with visible transitions.

### 3. UI Must Reflect Truth

The frontend should only present real execution truth from persisted backend state.

### 4. Recovery Is a First-Class Feature

Retry, resume, reconcile, and repair are core runtime behaviors, not afterthoughts.

### 5. Human Control Remains Central

The platform should accelerate the developer while keeping actions inspectable, reviewable, and overrideable.

## Target Architecture

High-level flow:

`User/UI -> API -> durable run record -> bootstrap planner/DAG -> queued work items -> worker execution loop -> artifacts/events -> GitHub/PR outputs -> live UI updates`

### Core Subsystems

#### A. Control Plane

Owns:

- projects
- tasks
- runs
- execution state
- activity and event logs
- replay and resume metadata

#### B. Bootstrap Planner

Owns:

- transforming a task or run into a concrete execution plan
- creating the initial DAG or work items durably
- assigning stage metadata
- recording bootstrap events

This must happen durably at run launch, not as a best-effort fire-and-forget side effect.

#### C. Execution Runtime

Owns:

- picking up queued work items
- tool invocation
- repo mutations
- test, build, and validation steps
- retries and failure handling

#### D. Workspace and Repo Layer

Owns:

- local workspace preparation
- branch creation
- patching
- commit and push
- repo map generation
- pull request generation and metadata

#### E. Event Stream and Timeline Layer

Owns:

- ordered run events
- current stage explanations
- worker status
- retries, failures, and blocking reasons
- artifact publication signals

#### F. UX and Mission Control Layer

Owns:

- run monitoring
- queued, running, and completed states
- artifact views
- empty states
- action gating
- human-readable operator context

## Required Lifecycle Model

A run should move through explicit lifecycle stages such as:

- `CREATED`
- `BOOTSTRAPPING`
- `PLANNING`
- `READY_FOR_EXECUTION`
- `EXECUTING`
- `RETRYING`
- `BLOCKED`
- `AWAITING_REVIEW`
- `COMPLETED`
- `FAILED`
- `CANCELED`

Exact names can vary, but the state model must be explicit.

Important rule:

A run should never remain in a vague queued state with zero work items and no recovery owner.

## Minimum Viable Proof Loop

Before expanding automation, the system needs one reliable proof loop:

1. create or select a task
2. launch a run from the task
3. bootstrap creates work items durably
4. workspace is prepared
5. branch is created
6. at least one real file is written or modified
7. commit is created and pushed to GitHub
8. pull request can be opened or prepared
9. Mission Control reflects the real state throughout

This is the first hard milestone. Many later features depend on it.

## What Real-Time Should Mean

Real-time does not mean holding a fragile HTTP request open forever.

It means:

- the API returns quickly with a run id
- the run continues independently in durable workers
- the UI polls or streams updates from persisted state
- the user can refresh and reconnect safely
- retries and failures are surfaced live
- the timeline reflects real state progression

This gives the user the feeling of a live working agent without coupling execution to browser or request lifetime.

## Gap Analysis

The current system already has meaningful pieces in place:

- tasks and runs exist
- Mission Control exists
- execution timeline exists
- repo connectivity exists
- runtime and worker concepts exist
- GitHub-directed output path exists

The biggest remaining gap is not product imagination. It is execution durability.

### Current Risks

- run startup depends on request-scoped kickoff behavior
- work items may not be durably seeded at launch
- external workers depend on work items already existing
- pre-execution states can look like failures in the UI
- some UX elements reveal internal assumptions too early

Meaning:

The product shell is ahead of the runtime guarantees.

## Roadmap

### Phase 1: Make One Path Fully Real

Goal: prove the system can complete a manual end-to-end software action.

Outcomes:

- launch bootstrap is durable
- work items appear immediately or predictably after launch
- queued runs cannot stay empty forever
- branch creation works
- file write works
- commit and push work
- pull request path is testable
- Mission Control reflects actual progress

Deliverables:

- durable run bootstrap in the launch path
- work-item creation regression test
- visible timeline milestones for bootstrap and execution
- branch and commit smoke test
- empty-state handling for pre-workspace and pre-strategy conditions

Exit criteria:

A user can run a task and see a real GitHub commit pushed by the system.

### Phase 2: Make the System Trustworthy

Goal: the UI tells the truth and the runtime recovers from common failures.

Outcomes:

- clear stage names and explanations
- retry and recovery states
- blocked-state explanations
- polling tuned to stage intensity
- no false error states for not-ready data
- timeline and pills or buttons are readable and stable

Deliverables:

- retry policy and retry event logging
- timeout and stalled-run handling
- repair path for stranded runs
- Mission Control status polish
- workspace, strategy, and repo map "not ready yet" states

Exit criteria:

Users can understand why a run is waiting, retrying, blocked, or completed without reading logs.

### Phase 3: Add Operator-Grade Controls

Goal: help developers steer and inspect runs instead of just watching them.

Outcomes:

- replay, rerun, and resume
- compare runs
- inspect strategy choices
- inspect generated patches and artifacts
- selective approval gates
- reviewable pull request handoff

Deliverables:

- run replay model
- artifact comparison view
- structured run summary
- pull request readiness status
- operator override controls

Exit criteria:

A developer can guide, compare, and recover runs without dropping into backend internals.

### Phase 4: Add Deeper Automation

Goal: layer autonomy only after the manual path is solid.

Outcomes:

- auto-retry categories
- auto-continue on safe steps
- planner heuristics
- smarter task decomposition
- quality and risk scoring
- agent-to-agent coordination where justified

Deliverables:

- confidence model based on real evidence
- safe automation rules
- auto-escalation for blocked states
- recovery heuristics

Exit criteria:

Automation increases throughput without reducing trust.

## What Can Be Hard-Coded Now vs Real Later

### Safe to Hard-Code Temporarily

- stage description text
- next-step helper copy
- empty-state messaging
- timeline wording
- confidence band labels for UI scaffolding
- disabled-state explanations

### Must Come From Real Backend Truth

- work-item count
- workspace readiness
- branch existence
- commit existence
- pull request status
- artifact count
- run completion or failure state
- retry and failure reasons

Rule:

Hard-code the user guidance, not the execution truth.

## Event Model Recommendation

Every meaningful runtime action should emit a persisted event.

Suggested events:

- `RUN_CREATED`
- `RUN_BOOTSTRAP_STARTED`
- `RUN_DAG_CREATED`
- `WORK_ITEMS_SEEDED`
- `WORKSPACE_PREPARED`
- `BRANCH_CREATED`
- `PATCH_GENERATED`
- `TESTS_STARTED`
- `TESTS_FAILED`
- `RETRY_SCHEDULED`
- `COMMIT_CREATED`
- `PUSH_COMPLETED`
- `PR_CREATED`
- `RUN_BLOCKED`
- `RUN_COMPLETED`
- `RUN_FAILED`

This supports:

- Mission Control timeline
- analytics
- debugging
- replay and recovery
- user trust

## Reliability Requirements

### Idempotency

Repeated launch or replay operations should not create uncontrolled duplicate side effects.

### Reconciliation

The system should detect stranded runs such as:

- queued but no work items
- running but no event progress for too long
- workspace expected but missing

### Retry Semantics

Retry should be intentional and observable.

### Checkpointing

After each major step, enough state should be persisted to continue later.

### Separation of Concerns

Bootstrap should be distinct from execution.
Execution should be distinct from UI presentation.

## Mission Control UX Principles

### Show What Is Happening Now

Every run needs a clear current stage and next expected step.

### Show What Is Missing

If a panel depends on future runtime outputs, show a not-ready state instead of a red error.

### Reduce Noisy Refresh

Polling should adapt to state:

- slower when queued
- faster when actively executing
- reduced when the user is reading or the tab is hidden

### Preserve User Context

Do not aggressively reset tabs, timeline position, or selected details during refresh.

### Make Controls Readable

Status pills, filters, and action buttons should always have visible labels and strong contrast.

## Suggested Product Language

Use language that sounds operational and clear:

- "Bootstrapping run"
- "Planner is creating work items"
- "Waiting for worker pickup"
- "Preparing local workspace"
- "Applying patch to branch"
- "Pushing commit to GitHub"
- "Blocked on validation failure"
- "Awaiting review before PR creation"

Avoid vague messages like:

- "Queued" without explanation
- "No data" when the system simply is not ready yet
- hard errors for expected pre-output states

## Metrics That Matter

Track these as the system matures.

### Core Reliability

- run bootstrap success rate
- runs with zero work items after launch
- median time to first work item
- median time to first artifact
- median time to first commit
- run completion rate

### Product Trust

- number of stranded runs
- number of manual retries required
- pull request creation success rate
- false-error rate in Mission Control

### Developer Value

- time from task launch to first usable output
- time from run launch to GitHub push
- percent of runs producing reviewable code changes

## Immediate Next Actions

After the current fix lands:

1. validate the full manual flow
2. record the exact successful lifecycle
3. patch remaining truth gaps in Mission Control
4. only then expand automation

### Manual Flow Validation

- create task
- run task
- observe work items
- confirm branch created
- confirm file change committed
- confirm push to GitHub
- confirm pull request path is reachable

### Lifecycle Recording

- statuses seen
- events emitted
- artifacts created
- branch, commit, and pull request proof

### Mission Control Truth Gaps

- empty states
- polling
- styling
- stage explanations

## Final Takeaway

The system does not need a new grand vision. The vision is already strong.

What it needs now is execution discipline:

- durable bootstrap
- observable runtime state
- truthful UX
- one complete GitHub proof loop

Once that exists, the platform can move from a promising shell to a real developer operator and then expand into deeper automation without losing trust.
