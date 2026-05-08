# Recovery Tiered Model Routing

Date: 2026-05-08

## Problem

Autonomous recovery currently behaves too much like another normal agent step. If the main run has already burned through its execution budget, recovery can be queued and then immediately blocked before it attempts a fix.

Observed example:

- Run `0b0df1b3-cc47-4f54-8e51-25b94117a8c8` failed in `RUN_TESTS`.
- Recovery correctly queued `FIX_TEST_FAILURE_1`.
- The fix node failed with `run_budget_exhausted`.
- The actual failure was a small generated-test bug in `test_index_html.py`.

The result was technically correct budget enforcement, but poor recovery behavior: the system knew the next step and could not execute it.

## Design Principle

Recovery should be routed by failure class, cost risk, and required reasoning depth before selecting a model.

Do not hardcode provider names into workflow logic. The workflow should request a capability tier, and deployment config should map that tier to OpenAI, Gemini, Groq, or another provider.

## Failure Classifier

Every failed work item should produce a normalized failure class before recovery routing:

- `clone_auth_failure`: Git clone, host key, GitHub App, token, installation, or repo URL failure.
- `environment_failure`: missing binary, missing dependency, path issue, shell/env mismatch.
- `syntax_failure`: parser, syntax, indentation, import, or test collection failure.
- `dependency_failure`: missing package, lockfile, install, version mismatch.
- `test_assertion_failure`: tests ran and assertions failed.
- `policy_failure`: architecture contract, protected zone, budget, or approval gate.
- `multi_file_behavior_failure`: behavior failure likely requiring cross-file reasoning.
- `unknown_failure`: insufficient structured evidence.
- `budget_exhausted`: recovery cannot proceed without budget escalation or a new run.

The classifier should use deterministic signals first:

- command exit code
- pytest collection vs assertion output
- git clone stderr
- work-item type/status
- execution contract budget state
- repo preflight result
- changed-file list and target-file scope

Use a cheap model only when deterministic classification is ambiguous.

## Recovery Tiers

### Tier 0: Deterministic Recovery

No model call.

Use for:

- retrying transient shell/network commands
- repo preflight and auth strategy checks
- stale worker detection
- host key setup guidance
- simple generated-test structural repairs that can be identified safely

Examples:

- `auth_mode=ssh` but repo preflight says `public_https/plain`: check stale worker rows.
- `NameError` caused by executable test logic inside a parser class body: move executable logic into a standalone `test_*` function or request a narrow generated-test repair.

### Tier 1: Cheap Recovery

Fast, low-cost model.

Use for:

- path fixes
- small env fixes
- simple import fixes
- command recommendation
- narrowing failure context

Context budget should be tiny: stack trace, target file snippets, command, and changed-file list.

### Tier 2: Code Repair

Medium code model.

Use for:

- syntax repair
- dependency resolution
- generated test repair
- one-file implementation or test fixes
- failed assertions with clear stack traces

Context should include:

- failing command and output
- relevant file snippets
- current diff
- target/allowed file list
- previous recovery attempts

### Tier 3: Architectural Recovery

Premium reasoning model.

Use for:

- multi-file behavior failures
- unclear root cause after deterministic and Tier 1/Tier 2 attempts
- contract conflicts
- refactor planning
- semantic graph reasoning
- failures spanning implementation, tests, and project architecture

Tier 3 should be opt-in by policy or budget state, not the default.

## Budget Partitioning

Recovery needs a reserve. A single shared run budget makes the most important step run out of money.

Recommended starting split:

- planning: 15-20%
- implementation: 40-45%
- validation: 15-20%
- recovery reserve: 20-25%

The execution contract should track these separately:

- `main_budget`
- `validation_budget`
- `recovery_budget`
- `manual_escalation_budget`

If main budget is exhausted but recovery reserve remains, `FIX_TEST_FAILURE` can still run.

If all recovery budget is exhausted, the system should stop with a product-visible state:

```text
Recovery available but blocked by budget. Increase recovery budget, fork with a higher cap, or manually repair the workspace.
```

## Provider-Agnostic Model Router

Workflow code should request a tier, not a vendor:

```text
deterministic
cheap_recovery
code_repair
architectural_recovery
```

Deployment config maps tiers to concrete providers/models:

```text
cheap_recovery = groq-fast | gemini-small | openai-small
code_repair = gemini-pro | openai-medium | claude-sonnet-class
architectural_recovery = strongest configured reasoning model
```

The routing decision should be recorded on the AI job:

- failure class
- selected recovery tier
- provider/model
- deterministic signals used
- budget partition used
- reason for escalation or refusal

## Stop States

Failure states should distinguish cause from policy:

- `FAILED_TESTS`: validation failed.
- `RECOVERY_QUEUED`: fix path exists.
- `RECOVERY_BLOCKED_BUDGET`: fix path exists but budget does not allow it.
- `RECOVERY_BLOCKED_POLICY`: fix path violates scope/contract.
- `RECOVERY_NEEDS_HUMAN`: system lacks enough confidence.
- `RECOVERY_EXHAUSTED`: max attempts reached.

The UI should not collapse all of these into `FAILED`.

## Implementation Notes

1. Add a failure classifier before `plan_recovery`.
2. Add deterministic recovery handlers for repo/auth/env/path and common generated-test structure issues.
3. Split execution budget into main, validation, and recovery reserves.
4. Route recovery through model capability tiers.
5. Persist routing evidence in `ai_job_runs.details`.
6. Surface budget-blocked recovery distinctly in Mission Control.

## Acceptance Criteria

- A public HTTPS repo clone issue never invokes premium model reasoning before repo preflight and worker freshness checks.
- A pytest collection failure from generated tests routes to deterministic or Tier 2 code repair.
- A run that exceeds main implementation budget can still spend a configured recovery reserve.
- If recovery cannot run because budget is exhausted, Mission Control says that explicitly.
- Provider changes do not require workflow code changes.
