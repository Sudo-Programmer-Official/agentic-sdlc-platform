# Stabilization Checklist

This is the trust gate for the current phase:

`stabilize -> harden -> trust`

No new capabilities should outrank failed checklist items in this document.

The goal is simple:

- reduce variance
- reduce surprises
- increase clarity
- increase confidence

This checklist is organized into six engineering layers:

1. execution reliability
2. repo understanding
3. patch safety
4. observability
5. user trust surface
6. infrastructure stability

## Exit Condition

The platform is ready to widen scope only when:

- the core loop passes consistently
- failures are bounded and explainable
- review surfaces are complete
- repo-backed execution is safe
- the system feels predictable, not clever

## Canonical Loop

The system must reliably complete this cycle:

`goal -> plan -> locate files -> modify code -> validate -> review -> PR`

If the run fails, it must still fail cleanly and explain why.

---

## 1. Execution Reliability

This is the first release gate. If this layer is not solid, nothing above it matters.

### Core loop checks

- [ ] workspace is created per run
- [ ] branch is created per run or run fork
- [ ] tasks are isolated per run
- [ ] retries are bounded
- [ ] task timeout behavior is explicit
- [ ] cleanup policy is explicit
- [ ] no run is left half-finished without a visible terminal state

### Runtime state checks

- [ ] `alembic current` matches `alembic heads`
- [ ] production DB is at the expected head revision
- [ ] repository connection persists correctly
- [ ] workspace manifest includes repo, branch, and context metadata
- [ ] command audit log exists in `logs/commands.jsonl`
- [ ] workspace writes stay inside the workspace root

### End-to-end completion checks

- [ ] patch artifacts are produced for repo-editing runs
- [ ] diff preview loads for latest patch artifact
- [ ] PR flow can finish once approval is granted
- [ ] retained workspaces remain inspectable when cleanup policy is `retain`

### Failure handling checks

- [ ] failed runs stop with a clear reason
- [ ] repeated identical failures do not spin indefinitely
- [ ] recovery path is visible when healing occurs
- [ ] failure leaves enough information to diagnose what happened

Example of acceptable failure messaging:

> Patch failed because `Button.vue` changed after the run started.  
> Suggested fix: restart the run against the updated branch.

---

## 2. Repo Understanding

This is the “Codex feels smart” layer. The system should understand the repo before editing.

### Repo map checks

- [ ] repo map loads for repo-backed projects
- [ ] repo-map search finds obvious targets like login component / auth service
- [ ] operator can answer repo-structure questions from repo map
- [ ] repo understanding works without loading the whole repo into context

### Indexed knowledge checks

- [ ] indexed files include path and lightweight summary
- [ ] indexed symbols/features are useful enough to route a narrow request
- [ ] common file locations are discoverable across repeated runs
- [ ] repo knowledge remains project-scoped, not cross-project by accident

### Reuse checks

- [ ] before editing, the system can detect when a feature likely already exists
- [ ] before editing, the system can detect when a similar run already solved a related issue
- [ ] repo-aware queries are grounded in real files, not model guesses

---

## 3. Patch Safety

The agent must never edit code blindly.

### Patch risk checks

- [ ] files changed count is visible before PR
- [ ] additions/deletions are visible before PR
- [ ] changed files are extractable from the patch
- [ ] patch explanation is available before approval

### Risk signaling checks

- [ ] low-impact UI-only changes are distinguishable from broad system changes
- [ ] multi-file or multi-module edits are visibly riskier
- [ ] approval gate blocks PR creation until patch is approved

### Validation checks

- [ ] every patch is paired with validation output or a visible lack of validation
- [ ] build/test outcome is visible in the run path
- [ ] impact information is available for the latest patch

### Determinism checks

- [ ] same narrow request produces similar likely files across repeated runs
- [ ] likely validation steps are explicit before editing
- [ ] open-ended requests are narrowed or rejected instead of guessed

---

## 4. Observability

Every run should tell a story.

### Timeline checks

- [ ] latest run has a readable replay timeline
- [ ] timeline shows creation, execution, failure/recovery, artifacts, and PR events
- [ ] timeline ordering is deterministic
- [ ] replay is reachable from Mission Control without dead ends

### Task queue checks

- [ ] live task queue shows queued/running/done/failed states clearly
- [ ] each task shows progress and current log line
- [ ] related artifacts stay attached to task cards
- [ ] empty states explain what the user should do next

### Operator observability checks

- [ ] AI Operator answers are grounded in actual tool outputs
- [ ] unsupported requests are rejected clearly
- [ ] references link back into system objects
- [ ] operator never invents run, artifact, PR, or workspace state

### Failure story checks

- [ ] a failed run still leaves a readable path of what happened
- [ ] latest failed step is visible
- [ ] affected artifact/run is visible
- [ ] review surfaces still load where possible after failure

---

## 5. User Trust Surface

This layer determines whether humans will trust the system.

### Mission Control checks

- [ ] Mission Control surfaces project, latest run, workspace status, and repo state
- [ ] compare, replay, fork, and PR flows are reachable from the main page
- [ ] warnings and partial-failure alerts are visible
- [ ] the page feels like a workbench, not a static report

### Review surface checks

- [ ] review surface shows file count, diff size, preview state, approval state, and PR state
- [ ] operator can preview diff before approval
- [ ] operator can explain patch before approval
- [ ] accept / reject / request-modification actions are understandable

### Comparison and memory checks

- [ ] compare original vs fork is readable
- [ ] comparison shows outcome, elapsed time, recoveries, artifacts, file deltas, and PR result
- [ ] quick-read comparison summary is understandable at a glance
- [ ] run memory returns useful similar runs without blocking runtime

### Plan and explanation checks

- [ ] likely files and validation steps are explainable before editing
- [ ] users can inspect why a patch exists
- [ ] users can inspect why a run failed
- [ ] users can inspect what changed and whether it is safe

---

## 6. Infrastructure Stability

This layer keeps the system survivable as usage grows.

### Queue and worker checks

- [ ] worker crashes do not leave runs in ambiguous states
- [ ] retries are bounded and visible
- [ ] run coordination does not depend on intelligence-plane queries
- [ ] execution-plane import guard passes

### Execution vs intelligence separation checks

- [ ] execution plane does not import intelligence or control-plane services directly
- [ ] `apps/api/tests/test_execution_plane_imports.py` passes
- [ ] graph-heavy reads stay off runtime hot paths

### Safe command execution checks

- [ ] workspace commands are allowlisted
- [ ] dangerous shell operations are unavailable to executors
- [ ] command execution remains auditable after the run
- [ ] failed commands preserve enough output for diagnosis

### Performance targets

These are target thresholds, not guarantees yet:

- [ ] repo analysis feels close to `< 5s`
- [ ] task planning feels close to `< 3s`
- [ ] patch generation feels close to `< 10s`
- [ ] PR creation feels close to `< 5s`
- [ ] end-to-end narrow run feels close to `15–30s`

### Metrics to track

These should be visible internally before widening scope:

- [ ] task success rate
- [ ] PR acceptance rate
- [ ] patch rollback rate
- [ ] average run time
- [ ] retry rate

If task success stays below `80%`, improve reliability before expanding workflow scope.

---

## Canonical Smoke Test

Run this exact flow on a real repo-backed project:

1. Connect repository
2. Verify repo metadata in Project Overview / Mission Control
3. Start a run
4. Confirm workspace is created and repo-backed
5. Trigger a run that produces a patch artifact
6. If failure occurs, confirm replay and recovery visibility
7. Explain the patch artifact
8. Preview the diff
9. Approve the patch
10. Create a PR
11. Fork the run
12. Compare original vs fork
13. Query run memory / similar runs
14. Use AI Operator to ask:
   - why did the latest run fail?
   - explain the latest patch
   - compare the last two runs
   - show workspace status
   - show repo map

The flow is only considered stable if it completes cleanly or fails cleanly.

---

## What To Avoid During Stabilization

Do not prioritize:

- new AI capabilities
- broader task classes
- multi-agent orchestration
- autonomous deploys
- open-ended tasks with weak review
- additional automation layers that increase variance

During this phase, every proposed change should answer:

`Does this make the system easier to trust?`

- If yes, prioritize it.
- If not, postpone it.

---

## Product Rule For This Phase

The product should feel like:

- it understands the repo
- it plans carefully
- it edits safely
- it shows its work
- it does not surprise the user

That is the real stabilization bar.
