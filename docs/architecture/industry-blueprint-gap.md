# Industry Blueprint vs Current Repo

This document compares the current platform against the production-grade architecture pattern used by serious AI engineering operators.

Its purpose is not to invent new scope. It exists to identify the specific hardening work needed to move the current repo from:

`strong prototype architecture`

to:

`trustworthy engineering operator`

## Target Blueprint

The target production sequence is:

1. deterministic plan
2. deterministic retrieval
3. deterministic validation
4. stronger replay and review
5. broader autonomy only after the first four are stable

The ideal operator loop is:

`request -> plan -> retrieve -> patch -> verify -> preview -> PR -> human review`

## Current Repo Snapshot

The repo already has most of the major layers:

- operator/control plane
- run orchestrator and work-item DAG
- workspace-backed execution
- bounded command execution
- diff preview and artifact explainability
- replay/timeline
- run memory and comparison
- approval-gated PR creation

The main gap is not missing layers. It is tightening the contracts between those layers so behavior becomes deterministic and reviewable.

## Gap Matrix

| Blueprint Capability | Current Repo State | Main Gap | Priority |
| --- | --- | --- | --- |
| Deterministic plan artifact | Partial | no first-class patch plan per run | `P0` |
| Bounded repo retrieval contract | Partial | repo understanding is still mostly fresh scan + live read | `P0` |
| Per-project validation contract | Partial | validation commands and preview/build rules are not first-class project policy | `P0` |
| Strong replay/review narrative | Partial | replay exists, but plan/scope/verification narrative is not explicit enough | `P1` |
| Release metrics and trust gate | Partial | docs exist, but product-level release metrics are not yet codified into acceptance gates | `P1` |
| Broader autonomy | Intentionally deferred | should not expand before the first five tighten | `Later` |

## 1. Deterministic Plan Artifact

### What the blueprint expects

Every run should have an explicit plan artifact containing:

- goal
- intent
- subsystem
- primary files
- dependent files
- validation steps
- risk/confidence

### Current repo state

The repo already has planning signals, but they are scattered:

- runs and work items carry execution structure
- strategy planner exists
- Mission Control surfaces runtime and review state

What is missing is a single plan object that becomes the contract for the run.

### Exact hardening tasks

1. Add a first-class run plan schema/read model.
2. Store planned files, validation steps, and risk tier on the run.
3. Surface the plan in Mission Control and the Operator Dashboard before patch review.
4. Require the rest of the pipeline to reference that plan instead of inferring from ad hoc state.

### Acceptance criteria

- every repo-editing run has a visible plan
- plan includes target files and validation steps
- run replay can reference the original planned scope
- review UI can compare planned files vs changed files

## 2. Deterministic Retrieval Contract

### What the blueprint expects

Before editing code, the system should use a bounded retrieval contract:

- symbol lookup
- dependency expansion
- file verification
- explicit context size limits

### Current repo state

Current repo understanding is mostly:

- `rg`
- targeted file reads
- lightweight repo map summaries
- graph context from runtime data

This is workable, but still rebuilds too much understanding per task.

### Exact hardening tasks

1. Add a persistent symbol index.
2. Add dependency/test linkage tables.
3. Add impact-scope detection with depth and file caps.
4. Keep live verification after cache lookup.
5. Feed the model a compressed context envelope instead of broad file reads.

### Acceptance criteria

- file discovery no longer depends solely on fresh scan
- symbol lookup and impact expansion stay within configured caps
- context assembly is explainable and bounded
- repo-aware requests can say “this likely already exists here” with grounded evidence

## 3. Per-Project Validation Contract

### What the blueprint expects

Each project should define how work is validated:

- build command
- test command
- lint/typecheck commands
- preview eligibility
- health-check expectations

### Current repo state

There is partial validation configuration:

- global test command exists
- repo/workspace execution exists
- review surfaces show validation outcomes when artifacts exist

But validation policy is not yet a first-class project contract.

### Exact hardening tasks

1. Add per-project validation/preview profile.
2. Make build/test/lint/preview rules project-scoped rather than globally inferred.
3. Make preview creation conditional on validation success.
4. Surface validation policy in the operator/control plane.

### Acceptance criteria

- each repo-backed project has explicit validation commands
- validation steps are visible before execution
- preview is skipped or triggered according to project policy
- PR creation clearly references validation evidence

## 4. Stronger Replay and Review

### What the blueprint expects

Replay and review should show a full execution narrative:

- what was planned
- what files were inspected
- what scope was chosen
- what verification ran
- what changed
- what was delivered

### Current repo state

The repo already has:

- timeline/replay
- diff preview
- artifact explainability
- compare/fork/memory
- approval-gated PR review

The gap is that the narrative is still more event-driven than operator-intent-driven.

### Exact hardening tasks

1. Add an execution narrative read model.
2. Include plan, inspected files, scope, verification, and PR summary in that narrative.
3. Show confidence and risk explicitly in review surfaces.
4. Make low-risk vs high-risk paths obvious in UI.

### Acceptance criteria

- a developer can answer “what did the system do and why?” from one screen
- plan, diff, verification, and PR state are connected in one narrative
- failed runs still explain what happened in plain engineering terms

## 5. Release Metrics and Trust Gate

### What the blueprint expects

The system should be judged by stable release metrics, not by demos:

- success rate
- retry rate
- recovery rate
- PR quality / mergeability
- preview success rate
- time to reviewable output

### Current repo state

The repo already has:

- architecture guardrails
- stabilization checklist
- scorecard

But the release gate is still mostly policy, not yet an operational metric discipline.

### Exact hardening tasks

1. Define target thresholds for success, retries, and PR quality.
2. Add metric collection for run outcomes and validation outcomes.
3. Treat failed trust-gate metrics as blockers for scope expansion.
4. Add the canonical smoke test as a release ritual, not just documentation.

### Acceptance criteria

- release decisions can point to explicit trust metrics
- widening scope is blocked if baseline reliability falls
- the team can tell whether the platform is becoming more or less trustworthy

## Recommended Hardening Order

Do these in order:

1. deterministic plan artifact
2. deterministic retrieval contract
3. per-project validation contract
4. stronger replay/review narrative
5. release metrics and trust gate

Do not invert this order.

The repo should not widen into broader autonomy, multi-agent planning, or unrestricted preview/deploy flows until the first five are stable.

## Immediate Next Tasks

The next concrete hardening tasks for this repo are:

1. add first-class patch plan artifact per run
2. add symbol cache + dependency/test linkage
3. add scope guard + patch guard + risk gating
4. add structured verification findings before PR path
5. add project preview/validation profile

The runtime stage target for those changes is defined in:

- [`docs/architecture/runtime-execution-graph-spec.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/runtime-execution-graph-spec.md)

## What Not To Do Yet

Do not prioritize these before the gaps above are closed:

- multi-agent coordination
- broad autonomous refactors
- unrestricted repo mutation
- automatic production deploys
- giant semantic graph systems

Those all widen capability faster than they widen trust.

## Related Docs

- [`docs/architecture/ai-engineering-agent-scorecard.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/ai-engineering-agent-scorecard.md)
- [`docs/architecture/stabilization-checklist.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/stabilization-checklist.md)
- [`docs/architecture/production-agent-design-principles.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/production-agent-design-principles.md)
- [`docs/architecture/continuous-repo-understanding-v1.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/continuous-repo-understanding-v1.md)
