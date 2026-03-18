# Software Execution Cockpit Implementation Epics

See also: `docs/software-execution-cockpit-blueprint.md`, `docs/run-console-product-spec.md`, `docs/network-and-recovery-architecture.md`, `docs/agent-runtime-vision-roadmap.md`, `docs/architecture-profile-engineering-spec.md`, and `docs/engineering-memory-system-spec.md`. This document converts the cockpit blueprint into implementation epics with concrete scope, dependencies, acceptance criteria, and rollout order.

## Objective

Turn the current visible runtime foundation into an architecture-aware, multi-agent software execution cockpit with human control.

The delivery order should optimize for:

- architecture clarity before autonomy
- truth before polish
- verification before broad automation
- approval and recovery before risky side effects

## Guiding Rules

- Do not add more agent autonomy until the run state is visible and truthful.
- Do not add more model roles until task routing and architecture boundaries are explicit.
- Do not add more mutation power until approval and verification are enforceable.
- Do not rely on chat context as project memory; persist it as structured project state.

## Epic Sequence

### Epic 1: Architecture Profile Foundation

#### Goal

Create a durable project-level architecture profile so the runtime stops guessing repo structure, boundaries, commands, and safe zones.

#### Why first

Architecture stability is the multiplier for every later agent step. Without it, routing, planning, implementation, and review all drift.

#### Scope

- project-level architecture profile model
- repo layout and package ownership map
- service and boundary definitions
- safe refactor zones
- do-not-touch zones
- preferred commands and test recipes
- release and deploy assumptions
- initial UI to inspect and edit the profile

#### Backend deliverables

- `architecture_profiles` schema or equivalent project-bound model
- APIs to read and update profile sections
- derived maps:
  - module ownership
  - repo layout summary
  - validation recipe map
  - integration surface map

#### Frontend deliverables

- Architecture Profile screen
- editable sections for:
  - repo structure
  - boundaries
  - commands
  - safe and forbidden zones
- read-only summary card in Mission Control and Project Overview

#### Acceptance criteria

- each project can persist an architecture profile
- the runtime can read architecture profile data during planning
- Mission Control can show architecture assumptions for the active run
- dangerous or forbidden zones are queryable by the safety engine

#### Dependencies

- existing project model
- existing repo map and knowledge summary flows

#### Risks

- over-modeling the profile before enough real usage

#### Boundaries

- do not build full policy automation here
- do not yet add model arbitration

### Epic 2: Task Router and Role Allocation

#### Goal

Classify each request before execution and allocate the right model roles, context, risk level, and verification path.

#### Scope

- task classification
- ambiguity and risk scoring
- execution mode selection
- role plan generation
- context narrowing rules
- approval requirement prediction
- verification requirement prediction

#### Backend deliverables

- router output object persisted per run or task
- route fields:
  - task_type
  - ambiguity_level
  - risk_level
  - execution_mode
  - role_plan
  - approval_requirements
  - verification_requirements
- API to expose routing decision and reasoning summary

#### Frontend deliverables

- Task Router panel in task creation and run launch
- visible role assignment for:
  - planner
  - explorer
  - implementer
  - critic
  - verifier
  - narrator
- readable routing explanation in Mission Control

#### Acceptance criteria

- every AI-assisted run produces a persisted routing decision before execution
- the user can see which roles are active and why
- high-risk tasks route to stricter approvals and broader verification
- low-risk tasks can use narrower, faster flows

#### Dependencies

- Epic 1 architecture profile
- existing AI policy layer

#### Risks

- routing feels arbitrary if explanations are weak

#### Boundaries

- do not yet run multiple models in arbitration
- do not yet mutate approval state here

### Epic 3: Run Console and Environment Inspector

#### Goal

Complete the visible execution cockpit so users can see what the runtime is doing, where it is doing it, and what the environment truth is.

#### Scope

- live run console
- environment inspector
- richer action timeline
- stream health and reconnect status
- last confirmed heartbeat and worker state
- current hypothesis and next action copy

#### Backend deliverables

- environment context snapshot model
- run execution console enrichment:
  - current hypothesis
  - current role
  - active command
  - command output tails
  - target environment
  - service endpoint summary
  - secret presence summary
  - connectivity state summary
- event additions:
  - stream disconnected
  - stream reconnected
  - environment resolved
  - provider degraded
  - worker recovered

#### Frontend deliverables

- Run Console panel
- Environment Inspector panel
- health badges for:
  - UI connection
  - stream
  - worker
  - GitHub
  - LLM provider
  - last heartbeat
- reconnect and backfill banners

#### Acceptance criteria

- the user can answer "what is it doing right now?"
- the user can answer "which environment and services is it targeting?"
- disconnect or stream break does not make the run appear failed
- missed events can be replayed visibly after reconnect

#### Dependencies

- existing execution console
- existing workspace diagnostics
- network and recovery architecture plan

#### Risks

- too much data in one panel without prioritization

#### Boundaries

- do not add intervention mutations until the UI truth surface is stable

### Epic 4: Approval and Verification System

#### Goal

Make risky changes approval-aware and verification-backed so the platform can mutate code safely.

#### Scope

- approval policy engine
- verification matrix
- required and optional check model
- approval-aware step continuation
- rerun verification actions
- blocking reason normalization

#### Backend deliverables

- approval rules bound to:
  - architecture zones
  - schema changes
  - dependency changes
  - destructive edits
  - wide refactors
- verification matrix model with rows for:
  - format
  - typecheck
  - lint
  - targeted tests
  - build
  - smoke
  - preview
  - manual QA
- APIs to approve, reject, retry, and continue

#### Frontend deliverables

- Approval and Verification surface in Mission Control
- approval queue with risk explanations
- verification matrix with status, duration, scope, and rerun controls
- explicit "waiting for approval" and "verification blocked" states

#### Acceptance criteria

- risky runs cannot proceed silently past required approval gates
- verification status is visible per run and per step
- the user can rerun scoped validations without rerunning the whole run
- the runtime can distinguish blocked, failed, and awaiting review states

#### Dependencies

- Epic 1 architecture boundaries
- Epic 2 routing outputs
- existing approval model and patch review surface

#### Risks

- too many approval prompts can slow the product

#### Boundaries

- prioritize bounded approval gates over broad manual review workflows

### Epic 5: Multi-Agent Critic and Arbitration Flow

#### Goal

Separate implementation from critique and surface disagreement when it materially improves safety or architecture quality.

#### Scope

- critic role
- architecture rule checks against proposed patch
- disagreement records
- recommendation synthesis
- visible arbitration state in Mission Control

#### Backend deliverables

- critic pass execution step
- arbitration record model
- result fields:
  - implementation verdict
  - critic verdict
  - disagreement reason
  - recommended path
- APIs to accept or override recommended path

#### Frontend deliverables

- Arbitration panel in Mission Control
- diff between "smallest patch" and "cleaner architectural patch" when available
- operator choice controls

#### Acceptance criteria

- the system can surface implementation-versus-architecture disagreement explicitly
- the user can see the recommended path and why
- the runtime can continue from an approved arbitration decision

#### Dependencies

- Epic 1 architecture profile
- Epic 2 role routing
- Epic 4 approval controls

#### Risks

- unnecessary dual-model cost on low-risk tasks

#### Boundaries

- arbitration should be opt-in or policy-triggered, not universal

### Epic 6: Recovery Engine and Pattern Memory

#### Goal

Make repeated failures faster to diagnose and safer to recover by combining recovery policy with project memory.

#### Scope

- failure fingerprinting
- recovery class mapping
- suggested next action generation
- history-aware fix guidance
- repeated-incident memory

#### Backend deliverables

- persisted failure fingerprints
- mapping between fingerprint and preferred recovery action
- project-level pattern memory store
- APIs for:
  - related incidents
  - suggested fixes
  - recovery recommendations

#### Frontend deliverables

- recovery suggestions in Mission Control
- "similar past incidents" panel
- one-click safe recovery actions where policy allows

#### Acceptance criteria

- repeated problem classes surface past fixes and safe next steps
- recovery actions preserve run truth and avoid duplicate side effects
- the user can see whether a recovery came from policy, history, or manual override

#### Dependencies

- network and recovery architecture
- existing recovery policy slice
- run memory or comparison primitives

#### Risks

- noisy suggestions if fingerprints are too coarse

#### Boundaries

- do not auto-apply broad historical fixes without approval

## Shared Runtime Workstreams

These workstreams cut across the epics and should be scheduled deliberately.

### Workstream A: State Model Normalization

Needed for:

- blocked versus failed versus awaiting review
- stream disconnected versus run failed
- worker alive versus stream stale

Outputs:

- normalized run states
- normalized step states
- normalized connectivity states

### Workstream B: Event Schema Expansion

Needed for:

- file exploration visibility
- command lifecycle visibility
- approval and arbitration visibility
- recovery and reconnect visibility

Outputs:

- canonical action and product event types
- event payload contract
- backfill and replay semantics

### Workstream C: Side-Effect Safety

Needed for:

- branch push
- pull request creation
- deployment triggers
- comments and notifications

Outputs:

- external operation keys
- reconciliation-before-retry rules
- dedup checks

### Workstream D: Connectivity and Lease Truth

Needed for:

- worker handoff
- reconnect banners
- stale stream handling
- orphan detection

Outputs:

- worker lease and heartbeat truth in the UI
- stream fallback behavior
- reconnect replay

## Recommended Delivery Order

1. Epic 1: Architecture Profile Foundation
2. Epic 2: Task Router and Role Allocation
3. Epic 3: Run Console and Environment Inspector
4. Epic 4: Approval and Verification System
5. Epic 5: Multi-Agent Critic and Arbitration Flow
6. Epic 6: Recovery Engine and Pattern Memory

Reason:

- architecture clarity must come before deeper autonomy
- routing must exist before role-specific execution becomes reliable
- visible runtime truth must exist before more approvals and arbitration are usable
- approval and verification must exist before broad mutation power
- recovery and pattern memory should build on explicit states, not implicit ones

## Release Gates

### Gate 1: Architecture-aware execution

The platform is ready for broader routing only when:

- architecture profile exists per project
- planner and router use it
- safety engine can query it

### Gate 2: Truthful cockpit

The platform is ready for richer approvals only when:

- run console is truthful
- environment inspector is live
- stream and worker state are distinguishable

### Gate 3: Safe mutation control

The platform is ready for cross-model arbitration only when:

- approval gates are enforced
- verification matrix is working
- rerun and continue semantics are stable

### Gate 4: Recovery-assisted scale

The platform is ready for broader autonomous recovery only when:

- side-effect dedup is in place
- recovery events are durable
- pattern suggestions are accurate enough to help more than they distract

## Product Metrics by Epic

### Architecture Profile

- percent of projects with profile coverage
- percent of runs using architecture data
- architecture violation rate

### Task Router

- routing accuracy by task type
- percent of runs with visible role plan
- approval prediction accuracy

### Run Console

- time to first visible action
- time to first command output
- false-stuck rate
- reconnect recovery success rate

### Approval and Verification

- percent of risky runs gated correctly
- verification completion rate
- percent of runs with explicit proof of success

### Arbitration

- percent of high-risk runs using critic pass
- disagreement rate
- operator acceptance rate for recommendations

### Recovery and Pattern Memory

- repeated-incident assist rate
- recovery success rate
- duplicate side-effect rate

## Immediate Next Build

If starting now, the first implementation sprint should target:

1. Architecture Profile data model and API
2. Mission Control Environment Inspector payload
3. Task Router persisted output
4. Approval and Verification state normalization

That creates the minimum foundation for the cockpit to become architecture-aware rather than only execution-visible.
