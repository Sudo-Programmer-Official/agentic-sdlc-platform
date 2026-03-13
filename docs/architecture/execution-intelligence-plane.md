# Execution Plane vs Intelligence Plane

This platform stays stable at scale by separating execution from intelligence.

## Rule

- Execution plane writes facts.
- Intelligence plane reads facts.
- Execution plane must not block on intelligence services.

## Execution Plane

These components run engineering work and must remain deterministic:

- `app/runtime/orchestrator.py`
- `app/runtime/worker_service.py`
- `app/runtime/*_executor.py`
- `app/runtime/recovery_policy.py`
- `app/services/workspace_supervisor.py`
- artifact creation and runtime event emission

Execution responsibilities:

- create and start runs
- prepare workspaces
- execute work items
- retry or recover according to runtime policy
- write artifacts and events
- finalize run state

Execution code must not query:

- run memory
- run comparison
- strategy planning
- replay analytics

## Intelligence Plane

These components help humans and higher-level control flows understand runs:

- `app/services/run_summary_builder.py`
- `app/services/run_memory.py`
- `app/services/run_comparison.py`
- `app/services/strategy_planner.py`
- `app/services/strategy_selection.py`
- replay and analytics services

Intelligence responsibilities:

- summarize runs
- compare runs
- find similar runs
- recommend strategies
- provide replay and analytics views

## Allowed Interaction Pattern

1. Execution emits run state, events, artifacts, and summaries.
2. Intelligence reads those records through read models.
3. Operators or top-level APIs may use intelligence outputs to launch new runs.

The execution loop itself must not depend on intelligence queries.

## Practical Guidance

When adding a feature, ask:

- Does this change how a run executes?
  - If yes, it belongs to the execution plane.
- Does this help humans or higher-level orchestration understand or choose between runs?
  - If yes, it belongs to the intelligence plane.

Keep graph-heavy reads, comparison, memory, and strategy selection on read-model services and cached context paths, not on scheduler or worker hot paths.

For the broader production constraints around bounded autonomy, reviewability, and safe product wedges, see:

- `docs/architecture/production-agent-design-principles.md`
