# Production Agent Design Principles

This platform is intended to be a trustworthy AI engineering operator, not an unconstrained autonomous demo.

The design goal is:

- high autonomy
- high visibility
- high control

The system should only become more autonomous after it is already observable, reviewable, and bounded.

## Why Agent Systems Fail

Developer agents usually fail in production for predictable reasons:

- weak problem framing
- poor repo grounding
- unbounded retry loops
- weak review surfaces
- mixed runtime and intelligence responsibilities
- no strong reuse of prior knowledge
- unsafe workspace execution

These failures produce impressive demos and fragile real-world behavior.

## Platform Split

This repo should keep three planes distinct.

### Execution Plane

This plane must stay deterministic.

Examples:

- run orchestrator
- workspace supervisor
- executors
- recovery engine
- artifact creation

Responsibilities:

- start runs
- prepare isolated workspaces
- execute work items
- emit events and artifacts
- apply bounded retries and recovery
- finalize run state

Execution code should be boring, predictable, and debuggable.

### Intelligence Plane

This plane can be smart and evolving, but it must remain outside runtime hot paths.

Examples:

- repo map
- graph context
- run summaries
- run memory
- run comparison
- strategy planning
- replay and analytics

Responsibilities:

- understand runs
- summarize runs
- compare runs
- find similar runs
- recommend strategies
- power operator responses

Intelligence should read facts from the system. It must not destabilize execution.

### Control Plane

This is the governed, human-facing layer.

Examples:

- Mission Control
- approvals
- review surfaces
- PR actions
- AI Operator
- Automation Map

Responsibilities:

- make automation visible
- surface diff, impact, confidence, and replay
- allow steering and approvals
- keep the human in the loop where needed

## The Seven Production Rules

### 1. Always plan before edit

Before code changes, define:

- objective
- likely files
- expected validation steps
- success criteria

### 2. Always isolate workspace

Every run must have:

- its own workspace
- its own branch
- disposable or isolated execution context

### 3. Always validate

Every change should be paired with:

- build result
- test result
- impact report

### 4. Always expose review

Humans must be able to inspect:

- diff
- impacted files
- explanation
- confidence
- preview state
- PR target

### 5. Always cap retries

The agent must not spiral.

Examples:

- max recovery loops
- max strategy pivots without approval
- stop on repeated identical failures

### 6. Always reuse known knowledge

Before changing code, check:

- does the feature already exist?
- has this bug already been fixed?
- is there a similar prior run?
- is there a known project pattern?

### 7. Always prefer narrow wins

A reliable, narrow workflow is more valuable than a broad, unstable one.

Early product wedges should favor:

- test-fix runs
- bug-fix runs
- small UI changes
- PRD to tasks

## Recommended Product Wedge

The safest initial wedge remains:

`governed autonomous bug-fix / test-fix runs`

Why:

- clear input
- clear validation
- clear review output
- clear ROI
- strong trust model

## Anti-Patterns To Avoid

Do not rush into:

- fully autonomous multi-repo self-direction
- unrestricted shell execution
- automatic production deploys
- open-ended tasks with weak review
- runtime blocking on intelligence queries

## What “Done” Looks Like For A New Feature

A feature is production-ready only if it preserves these properties:

- execution remains deterministic
- observability improves, not degrades
- a review surface exists
- retries are bounded
- repo/project scope is explicit
- workspace isolation is preserved
- the human can understand what happened

For a compact maturity readout across the five core agent patterns, see:

- `docs/architecture/ai-engineering-agent-scorecard.md`

## Repo Guardrail

For this repo, the working rule is:

- execution plane writes facts
- intelligence plane reads facts
- control plane explains and governs facts

New features should ask:

- Does this change how runs execute?
  - If yes, execution plane.
- Does this help understand, compare, remember, or recommend?
  - If yes, intelligence plane.
- Does this help humans review, approve, or steer?
  - If yes, control plane.

## Mechanical Enforcement

This repo already includes an import guard test that prevents execution-plane code from importing intelligence/control-plane services directly:

- `apps/api/tests/test_execution_plane_imports.py`

Keep that guard updated as new intelligence or control-plane modules are added.

## Stabilization Gate

The operational release checklist for this phase lives in:

- `docs/architecture/stabilization-checklist.md`

Use that checklist to decide whether the platform is ready to widen scope again.

## Repo Intelligence Evolution

The next practical repo-awareness blueprint for large codebases lives in:

- `docs/architecture/continuous-repo-understanding-v1.md`

Use that document to evolve repo understanding without overbuilding a full graph system too early.
