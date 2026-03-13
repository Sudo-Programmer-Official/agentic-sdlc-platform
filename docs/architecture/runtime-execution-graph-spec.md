# Runtime Execution Graph Spec

This document defines the concrete repo-specific execution graph the runtime should converge toward during stabilization.

It is intentionally a policy/specification, not a runtime rewrite.

The controlling rule is:

- one mutating lane
- many parallel verification lanes

That keeps the run workspace deterministic while still allowing faster validation and preview work.

## Design Rule

The execution graph must preserve these boundaries:

- `PLAN` and `PATCH_VERIFY` are bounded preflight stages
- `APPLY_PATCH` is the only mutating lane
- verification stages can run in parallel after patching
- preview/provisioning stages only run after validation succeeds
- approval and PR creation stay in the governance lane

## Target Graph

```text
PLAN
  ->
PATCH_VERIFY
  ->
APPLY_PATCH
  ->
  RUN_LINT
  RUN_UNIT_TESTS
  BUILD_FRONTEND
  BUILD_BACKEND
   \   |   / 
   VALIDATE_RESULTS
      ->
   CREATE_FRONTEND_PREVIEW
   CREATE_BACKEND_PREVIEW
       \        /
      SMOKE_TEST_PREVIEW
             ->
          APPROVAL
             ->
          CREATE_PR
```

## Node Classes

### Planning lane

- `PLAN`
- `PATCH_VERIFY`

These stages bound scope before code changes begin.

### Mutating lane

- `APPLY_PATCH`

This is the only lane allowed to mutate the run workspace.

Backend and frontend patch steps may exist as separate work items, but they must serialize through one run-scoped repo workspace.

### Verification lane

- `RUN_LINT`
- `RUN_UNIT_TESTS`
- `BUILD_FRONTEND`
- `BUILD_BACKEND`
- `VALIDATE_RESULTS`

These stages may fan out in parallel because they are read-only against the patched workspace.

### Provisioning lane

- `CREATE_FRONTEND_PREVIEW`
- `CREATE_BACKEND_PREVIEW`
- `SMOKE_TEST_PREVIEW`

These stages only run after validation succeeds and only if project preview policy allows them.

### Governance lane

- `APPROVAL`
- `CREATE_PR`

These stages are human-facing and should remain explicit control-plane actions.

## Mapping Current Work Item Types

The current runtime already has a smaller deterministic DAG. The present-to-target mapping is:

| Current Work Item Type | Target Node | Current State |
| --- | --- | --- |
| `PLAN_DAG` | `PLAN` | implemented |
| `REVIEW_DIFF` | `PATCH_VERIFY` | approximated |
| `CODE_BACKEND` | `APPLY_PATCH` | implemented |
| `CODE_FRONTEND` | `APPLY_PATCH` | implemented |
| `WRITE_TESTS` | `RUN_UNIT_TESTS` | implemented as part of validation path |
| `RUN_TESTS` | `RUN_UNIT_TESTS` | implemented |
| `FIX_TEST_FAILURE` | `RUN_UNIT_TESTS` recovery slice | implemented |
| `REVIEW_INTEGRATION` | `VALIDATE_RESULTS` | approximated |
| `APPROVAL` rows / approval APIs | `APPROVAL` | control-plane implemented |
| `create-pr` service/action | `CREATE_PR` | control-plane implemented |

The missing nodes are:

- `RUN_LINT`
- `BUILD_FRONTEND`
- `BUILD_BACKEND`
- `CREATE_FRONTEND_PREVIEW`
- `CREATE_BACKEND_PREVIEW`
- `SMOKE_TEST_PREVIEW`

These should be added only after the current bounded graph and guardrails remain stable.

## Dependency Rules

The graph must enforce these rules:

1. `PATCH_VERIFY` must complete before `APPLY_PATCH`
2. `APPLY_PATCH` must complete before any validation or build stages
3. `VALIDATE_RESULTS` is a join node over all required validation/build stages for the current run scope
4. preview creation depends on `VALIDATE_RESULTS`
5. `SMOKE_TEST_PREVIEW` depends on every preview node that was actually scheduled
6. `APPROVAL` depends on either:
   - `VALIDATE_RESULTS` when no preview is scheduled
   - `SMOKE_TEST_PREVIEW` when preview is scheduled
7. `CREATE_PR` depends on `APPROVAL`

## Skip Rules

The graph must support explicit skip rules instead of assuming every stage always runs.

### Frontend-only change

When planned/actual changed files stay inside frontend paths:

- skip `BUILD_BACKEND`
- skip `CREATE_BACKEND_PREVIEW`

### Backend-only change

When planned/actual changed files stay inside backend paths:

- skip `BUILD_FRONTEND`
- skip `CREATE_FRONTEND_PREVIEW`

### Docs/config-only change

When planned/actual changed files stay inside docs or low-risk config paths:

- skip `CREATE_FRONTEND_PREVIEW`
- skip `CREATE_BACKEND_PREVIEW`
- skip `SMOKE_TEST_PREVIEW`

### No preview profile

When project preview policy is missing or disabled:

- skip every preview/provisioning node

## Retry Policy

Retries must be bounded and node-specific.

### No broad retries

Do not restart the whole run because one node failed.

### Node-level retry policy

| Node | Max Retries | Policy |
| --- | --- | --- |
| `PLAN` | `0` | deterministic; requeue whole run if needed |
| `PATCH_VERIFY` | `0` | require confirmation or reduce scope |
| `APPLY_PATCH` | `0` | mutate only through bounded recovery paths |
| `RUN_LINT` | `1` | one transient retry |
| `RUN_UNIT_TESTS` | `2` | current `RUN_TESTS -> FIX_TEST_FAILURE -> RUN_TESTS` slice |
| `BUILD_FRONTEND` | `1` | one transient retry |
| `BUILD_BACKEND` | `1` | one transient retry |
| `VALIDATE_RESULTS` | `0` | stop and surface verification state |
| `CREATE_FRONTEND_PREVIEW` | `1` | one preview launch retry |
| `CREATE_BACKEND_PREVIEW` | `1` | one preview launch retry |
| `SMOKE_TEST_PREVIEW` | `1` | one preview health retry |
| `APPROVAL` | `0` | human gate |
| `CREATE_PR` | `0` | explicit action only |

## Why This Spec Exists

The current runtime is already DAG-based, but the graph policy is still implicit across:

- `dag.py`
- `orchestrator.py`
- `worker_service.py`
- recovery policy
- Mission Control

This spec makes the next hardening steps deterministic:

1. add formal scope/patch guards
2. add verification/build nodes without conflicting writes
3. add preview lifecycle behind explicit graph dependencies
4. keep one mutating lane while allowing faster parallel verification

## Immediate Next Use

Use this spec as the contract for:

- future work-item type additions
- skip-rule implementation
- preview stage rollout
- Mission Control “execution graph” rendering
- release-gate validation of the runtime
