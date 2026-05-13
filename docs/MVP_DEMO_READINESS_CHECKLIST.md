# MVP Demo Readiness Checklist

## Objective
Prove Agentic SDLC can reliably deliver real-world apps end-to-end with governance, recovery, and visible operator control.

## Demo App Sequence
1. Portfolio Website (golden path)
2. Restaurant Website
3. College Website
4. Car Rental Website
5. Data Pipeline Dashboard
6. AI Automation Console

## Exit Criteria (per app)
- Requirements graph approved and linked to tasks.
- Tasks generated and visible in queue with correct counts.
- Run starts from UI and status moves `PENDING -> RUNNING -> DONE/FAILED/BLOCKED` correctly.
- Mission Control shows active work item, queue size, retries, and ETA.
- Preview is available and usable on desktop and mobile.
- Validation runs scoped tests (no unrelated repo-wide test failures).
- Recovery can resume/fix/retry without manual DB intervention.
- Final output merged or committed on run branch with traceable lineage.

## Required Runtime Controls
- Single active `RUN_TESTS` per run.
- Deterministic test command selection by scope.
- Drift recovery fallback (`apply_patch -> write_file`) for layout-sensitive frontend.
- Explicit run pause reason and resume action in UI.
- Flattened strategy telemetry in events:
  - `selected_strategy`
  - `effective_strategy`
  - `transition_reason`
  - `drift_risk_score`
  - `execution_zone`

## Operator UX Acceptance
- Operator can see:
  - total tasks
  - queued tasks
  - in-progress task
  - blocked/failed task count
  - estimated completion time
- Operator can:
  - start one task
  - start queued tasks sequentially
  - pause run
  - resume run
  - retry failed node

## Stability Gates (global)
- 6/6 apps complete with no unrecoverable runtime dead-end.
- >= 90% task closure without manual code edits outside workflow.
- 0 critical UI regressions in Mission Control, Requirements, Project Overview.
- No secret leakage in logs/events.
- Demo script can be repeated from clean project creation.

## Demo-Day Runbook
1. Create new project from template requirement pack.
2. Approve requirements graph.
3. Generate tasks.
4. Start run from Mission Control.
5. Show queue/progress/ETA.
6. Show one recovery event and successful continuation.
7. Show preview + final commit/branch output.

## Suggested Tracking Table
| App | Requirements Approved | Tasks Generated | Run Completed | Preview OK | Tests OK | Recovery OK | Notes |
|---|---|---|---|---|---|---|---|
| Portfolio |  |  |  |  |  |  |  |
| Restaurant |  |  |  |  |  |  |  |
| College |  |  |  |  |  |  |  |
| Car Rental |  |  |  |  |  |  |  |
| Data Dashboard |  |  |  |  |  |  |  |
| AI Automation |  |  |  |  |  |  |  |
