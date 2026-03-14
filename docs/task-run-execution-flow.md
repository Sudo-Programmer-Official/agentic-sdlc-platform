# Task-To-Run Execution Flow

This note captures the explicit task-to-run binding introduced for manually created tasks so the behavior is easy to reference during future debugging and rollout checks.

## Summary

Manually created tasks are now runnable end-to-end directly from the task list.

Current operator flow:
1. User creates a task.
2. User selects `Run This Task` in the Tasks dialog.
3. Backend creates a run bound to that exact task.
4. Planner/runtime generates work items using the selected task context.
5. Executor can pick up the generated work items and continue execution.

## What Changed

- Run creation accepts `task_id`.
- Backend validates the selected task belongs to the current project and tenant.
- Run creation persists task linkage and emits `task.run.created` plus `RUN_CREATED` with `task_id`.
- DAG and work-item generation now use the selected task context from the bound run.
- Frontend exposes `Run This Task` in the Tasks dialog and passes `task_id` through the existing run API.

## Behavioral Outcome

- Manual tasks no longer depend on Work Intake to become executable.
- Work Intake remains document-derived.
- Task execution is now explicit and operator-driven instead of implicitly intake-driven.

## Verification Completed

- Focused API and runtime tests passed.
- Web build passed.

## Remaining Live Validation

- Deploy and smoke test: create task -> `Run This Task` -> work items created -> execution proceeds.
- Confirm repeat-run behavior is intentional for the same task.
- Confirm task-to-run linkage is visible enough in the UI for operators.

## Notes

- This change intentionally does not alter Work Intake semantics.
- The smallest correct fix was to make task execution explicit from the task list rather than changing intake sourcing.
