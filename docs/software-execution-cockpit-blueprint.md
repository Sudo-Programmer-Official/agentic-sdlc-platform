# Software Execution Cockpit Blueprint

See also: `docs/agent-runtime-vision-roadmap.md`, `docs/human-in-the-loop-runtime-roadmap.md`, `docs/run-console-product-spec.md`, `docs/network-and-recovery-architecture.md`, `docs/software-execution-cockpit-implementation-epics.md`, and `docs/engineering-memory-system-spec.md`. This document turns the higher-level roadmap into a concrete product blueprint for the architecture-aware, multi-agent workflow the platform should expose.

## Core Thesis

The product should not behave like a chatbot for coding.

It should behave like an operating system for AI-assisted software delivery.

That means:

- architecture-first
- run-visible
- model-coordinated
- approval-aware
- validation-backed
- recovery-safe

## The Workflow Being Productized

Today the orchestration layer still lives in the engineer's head.

The practical workflow looks like this:

1. the engineer defines direction
2. one model explores or edits
3. another model critiques or suggests
4. the engineer compares outcomes
5. the engineer decides what survives
6. the engineer runs or observes verification
7. the engineer protects architecture and prevents damage

The platform should absorb that glue layer and make it a first-class system.

## Product Goal

Replace:

- manually bouncing between ChatGPT, Codex, repo context, tests, diff checks, and decisions

With:

- one observable, architecture-aware, multi-agent execution workflow with human control

## Why This Matters

The biggest speed multiplier is not raw code generation.

It is architecture stability.

When architecture is unstable:

- context shifts
- tool choices become inconsistent
- fixes become fragile
- correction loops increase

When architecture is stable:

- the repo becomes legible
- task scope is clearer
- edits are more predictable
- AI becomes faster
- trust increases

That means architecture clarity is a product feature, not just an engineering preference.

## Product Surfaces

The platform should be organized around four primary surfaces.

### 1. Architecture Profile

This is the persistent project brain.

It should store:

- repo layout
- service boundaries
- package ownership
- naming conventions
- allowed patterns
- banned patterns
- data and event contracts
- integration surfaces
- safe refactor zones
- do-not-touch zones
- preferred commands and test flows
- release flow

This is what stops the agent from guessing how a codebase works.

### 2. Task Router

Every request should be classified before execution begins.

Example task classes:

- bug fix
- UI tweak
- scoped feature
- refactor
- architecture change
- integration issue
- deploy or environment issue
- native or mobile bug

The router should decide:

- task type
- ambiguity level
- risk level
- required architecture context
- model role allocation
- approval gates
- verification scope

This is how the system avoids treating every task like the same workflow.

### 3. Run Console

This is the visible execution cockpit.

It should show:

- files explored
- searches performed
- diffs generated
- commands executed
- tests and builds
- environment and target runtime
- current step
- blockers
- confidence
- next action

The run console is the "no hidden work" layer.

### 4. Approval and Verification System

This is how the platform protects the codebase and earns trust.

It should govern:

- risky edits
- broad refactors
- shared package changes
- schema changes
- dependency upgrades
- deployment actions
- unresolved model disagreement

It should also track:

- required validations
- optional validations
- environment needed for each check
- smoke flow coverage
- human QA requirements

## Supporting Layers

These surfaces need shared system layers underneath them.

### A. Role-Based Agent Workflow

The platform should explicitly separate AI roles.

Suggested roles:

- Planner: understands the request and proposes the approach
- Explorer: searches files and maps the relevant code
- Implementer: makes the code changes
- Critic: checks architectural fit and intent drift
- Verifier: runs tests, builds, and smoke checks
- Recovery Agent: classifies failures and proposes the safest next step
- Narrator: explains what happened in plain language

This is stronger than one undifferentiated model loop.

### B. Cross-Model Arbitration

The platform should support disagreement when it is useful.

Example outcomes:

- "Implementation passes tests, but architecture critic flags a boundary violation."
- "Option A is smaller. Option B is cleaner but broader."
- "Two valid fixes found. Recommended path: option A."

This should be surfaced as a premium operator experience, not hidden.

### C. Safety Engine

The safety engine should enforce rules such as:

- do not delete files without approval
- do not change architecture casually
- do not touch unrelated packages
- do not rewrite config without review
- ask before migrations
- ask before dependency upgrades
- revert or isolate when verification fails badly

This encodes the judgment layer the engineer currently provides manually.

### D. Recovery Engine

When runs fail, the system should:

- detect the failure class
- isolate the failing step
- retry safe steps only
- preserve run history
- avoid duplicate side effects
- suggest the exact next action

Recovery must be structural, not ad hoc.

### E. Pattern Memory

The project brain should accumulate reusable intelligence:

- common failure patterns
- preferred fixes
- module ownership
- environment map
- validation map
- deployment topology
- historical repairs

This is how local repo familiarity becomes a durable product capability.

## Module Blueprint

### Module 1: Architecture Lock

Purpose:

- stabilize execution by locking project assumptions

User defines:

- project structure
- boundaries
- safe patterns
- forbidden patterns
- expected commands
- expected test strategy

System outputs:

- architecture profile
- risk map
- do-not-touch zones
- preferred validation recipes

### Module 2: Smart Task Execution

Purpose:

- turn a natural-language request into a bounded execution plan

Outputs:

- goal summary
- scoped plan
- candidate files to inspect
- model role allocation
- risk level
- approval requirements
- validation plan

### Module 3: Multi-Agent Review

Purpose:

- separate implementation from critique

Flow:

1. planner proposes approach
2. implementer proposes patch
3. critic evaluates patch against architecture and scope
4. verifier validates
5. narrator summarizes

### Module 4: Run Console

Purpose:

- make work visible in real time

Should show:

- searches
- file inspection
- file edits
- command execution
- output tails
- environment state
- validation results
- current blocker
- next suggested action

### Module 5: Approval Gates

Purpose:

- keep the engineer in control where it matters

Required gates:

- destructive edits
- shared boundary changes
- schema changes
- risky refactors
- deployment actions
- low-confidence execution
- conflicting model recommendations

### Module 6: Verification Matrix

Purpose:

- prove the work, not just claim it

Each task should define:

- required checks
- optional checks
- target environment
- smoke flow coverage
- manual verification needs

### Module 7: Pattern Memory

Purpose:

- make repeated problem classes faster to diagnose and safer to recover

Should capture:

- repeated bug fingerprints
- favored fixes by project
- common architecture violations
- repeated env failures
- repeated recovery sequences

## Operator Experience

The product should make the engineer feel like a runtime director.

The AI system becomes:

- implementer
- explorer
- verifier
- recoverer
- reporter

The engineer stays responsible for:

- architecture direction
- approval decisions
- arbitration when tradeoffs appear
- release confidence

That is the correct division of labor.

## State Model

Each task should move through an explicit execution shape:

- interpreted
- scoped
- planned
- approved
- executing
- verifying
- blocked
- recovering
- completed
- rejected

Each stage should expose:

- owner role
- confidence
- risk
- artifact outputs
- verification state
- approval status

## Data Model Additions

### Project brain objects

- `architecture_profile`
- `module_ownership_map`
- `validation_map`
- `deployment_topology`
- `failure_patterns`
- `preferred_fixes`

### Task routing objects

- `task_type`
- `ambiguity_level`
- `risk_level`
- `execution_mode`
- `role_plan`
- `approval_requirements`
- `verification_requirements`

### Run visibility objects

- `run_console_state`
- `active_role`
- `action_feed`
- `validation_matrix`
- `operator_interventions`
- `arbitration_results`

## UI Surfaces

### Architecture Profile View

Show:

- service and package map
- safe and unsafe zones
- commands and validation recipes
- current project assumptions

### Task Router View

Show:

- classified task type
- chosen flow
- assigned roles
- risk and ambiguity
- expected validations
- approval gates

### Run Console View

Show:

- current goal
- files explored
- commands
- diffs
- tests
- environment
- blocker
- next action

### Approval and Verification View

Show:

- pending approvals
- risk explanations
- validation matrix
- unresolved conflicts
- rerun and continue options

## Phased Rollout

### Phase 1

Ship:

- Architecture Profile baseline
- Task Router baseline
- Run Console baseline
- first approval gates

Exit criteria:

- tasks are scoped against architecture, not just user text

### Phase 2

Ship:

- explicit model roles
- critic and verifier passes
- validation matrix
- approval-aware run continuation

Exit criteria:

- implementation, critique, and proof are separated cleanly

### Phase 3

Ship:

- cross-model arbitration
- recovery engine
- project pattern memory
- repeated-failure suggestions

Exit criteria:

- the system handles drift, disagreement, and repeated issues without collapsing into opaque retries

## Product Sentence

We are building a software execution cockpit: an architecture-aware, multi-agent, approval-controlled workflow that turns hidden human orchestration into a visible system.
