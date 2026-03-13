# AI Engineering Agent Scorecard

Use this scorecard to assess whether the platform is behaving like a trustworthy engineering operator instead of a fragile agent demo.

This scorecard is intentionally practical. It rates only the five core patterns that matter most for stabilization and trustworthy autonomy.

## Scoring Scale

- `0 Missing`: no meaningful implementation
- `1 Ad hoc`: isolated pieces exist, but not dependable
- `2 Emerging`: useful path exists, but gaps are still obvious
- `3 Usable`: works in the main path, but not fully hardened
- `4 Reliable`: production-ready for the intended wedge
- `5 Operator-grade`: strong, repeatable, well-governed behavior at scale

## Current Snapshot

As of March 13, 2026, the recommended current maturity for this repo is:

| Pattern | Score | Why |
| --- | --- | --- |
| Task Planner | `2` | Planning exists implicitly through runs, work items, strategies, and operator guidance, but there is no first-class patch-plan artifact with risk/confidence gating yet. |
| Execution Sandbox | `3` | Run-scoped workspaces, command allowlists, audit logs, repo-backed execution, and PR flow exist; isolation is solid, but container-backed execution is not the default backend. |
| Repo Intelligence | `2` | Repo understanding currently relies mostly on `rg`, targeted file reads, repo map summaries, and graph context. Persistent symbol/dependency intelligence is still pending. |
| Verification Engine | `3` | Diff preview, approvals, test/build artifacts, replay, PR gating, and review surfaces exist; the missing piece is a formal pre-apply patch verification loop. |
| Memory + Recovery | `3` | Run summaries, run memory, comparison, replay, strategy scoring, and a first self-healing slice exist; broader failure-class recovery and stronger repo memory are still needed. |

## Pattern Details

### 1. Task Planner

The planner converts a vague request into an executable engineering plan.

What good looks like:

- explicit goal and intent
- target subsystem
- primary and dependent files
- validation steps
- risk/confidence rating
- visible plan before code mutation

Current repo evidence:

- runs and work items provide structured execution units
- strategy planning exists for candidate runs
- Mission Control already surfaces execution state and review context

What is still missing:

- first-class patch plan artifact
- planned file list before patch generation
- explicit confidence/risk summary tied to the plan

### 2. Execution Sandbox

The sandbox keeps edits safe, isolated, auditable, and reproducible.

What good looks like:

- isolated workspace per run
- dedicated branch
- bounded commands
- audit trail for execution
- safe cleanup path
- no direct mutation of the source repo

Current repo evidence:

- workspace supervisor
- workspace command allowlist + command audit log
- repo-backed workspace execution
- branch/push/PR flow from workspace state

What is still missing:

- container-backed workspace backend
- stronger cleanup and quota enforcement at scale
- per-backend execution abstraction for local vs containerized workspaces

### 3. Repo Intelligence

Repo intelligence makes the agent feel aware of the codebase instead of merely reactive to search results.

What good looks like:

- persistent file inventory
- symbol index
- dependency/import edges
- test linkage
- impact scope detection
- hot subsystem cache

Current repo evidence:

- repo map service
- `rg`-driven targeted inspection
- graph context and artifact lineage
- operator can answer grounded repo questions

What is still missing:

- persistent symbol cache
- dependency/test linkage tables
- incremental repo refresh pipeline
- hot context cache for active subsystems

### 4. Verification Engine

Verification ensures the system produces trustworthy changes, not just plausible ones.

What good looks like:

- patch plan
- patch proposal
- verification findings
- build/test/lint evidence
- impact summary
- confidence score
- approval gate when risk is elevated

Current repo evidence:

- diff preview
- explain artifact
- approval-gated PR creation
- run comparison and replay
- build/test artifacts and review surfaces

What is still missing:

- formal patch verification step before execution
- structured verification findings stored per patch
- explicit confidence scoring tied to planned scope and observed validation

### 5. Memory + Recovery

Memory and recovery let the system reuse prior knowledge and converge after failure instead of repeating mistakes.

What good looks like:

- similar-run retrieval
- strategy comparison
- replayable run history
- bounded recovery loops
- failure classification
- reusable successful patch patterns

Current repo evidence:

- run summaries
- run memory
- run comparison
- strategy planner/selector
- replay/timeline
- self-healing `RUN_TESTS -> FIX_TEST_FAILURE -> RUN_TESTS retry`

What is still missing:

- broader recovery classes beyond test-fix flow
- stronger reuse of repo-local successful patch clusters
- tighter linkage between run memory and planned patch scope

## Stabilization Priority Order

During stabilization, improvements should follow this order:

1. strengthen execution sandbox reliability
2. add first-class planning artifacts
3. add lightweight repo intelligence
4. add formal patch verification
5. expand memory and recovery carefully

This order is deliberate. It preserves the rule:

- constrain first
- automate second
- generalize third

## Release Gate

The system should not be marketed as a broader autonomous engineering agent until all five patterns are at least `3`, and the first four are on a path to `4` for the target workflow.

The safest near-term wedge remains:

`governed autonomous bug-fix / test-fix / small patch runs`

## Related Docs

- [`docs/architecture/industry-blueprint-gap.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/industry-blueprint-gap.md)
- [`docs/architecture/execution-intelligence-plane.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/execution-intelligence-plane.md)
- [`docs/architecture/production-agent-design-principles.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/production-agent-design-principles.md)
- [`docs/architecture/stabilization-checklist.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/stabilization-checklist.md)
- [`docs/architecture/continuous-repo-understanding-v1.md`](/Users/abhishekkumarjha/Documents/sudo-programmer-official/agentic-sdlc-platform/docs/architecture/continuous-repo-understanding-v1.md)
