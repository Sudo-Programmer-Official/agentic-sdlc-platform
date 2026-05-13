# execution lifecycle example (sanitized)

1. requirement is approved in requirements view and linked to task/run context.
2. run is queued and workspace preparation is validated.
3. orchestrator generates execution DAG and emits bootstrap events.
4. worker claims eligible work item (dependency + capability checks).
5. executor performs stage action (`write_tests`, `write_code`, `run_tests`, `review_diff`).
6. artifacts and events are persisted; checkpoints captured after safe transitions.
7. on failure, recovery policy classifies error and selects recovery action.
8. bounded retry executes; validation determines forward progress.
9. successful run can publish branch/pr metadata; timeline and summaries are materialized.

Notes:
- This sequence reflects runtime services (`orchestrator.py`, `worker_service.py`, `recovery_policy.py`, `runtime_recovery_service.py`).
- No credentials, private keys, proprietary prompts, or private endpoints are included.
