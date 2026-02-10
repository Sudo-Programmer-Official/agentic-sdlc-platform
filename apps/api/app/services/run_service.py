from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from uuid import uuid4

from core.execution import AgentRegistry, AgentResult, AgentType, ExecutionContext
from core.ledger import ActionLedger
from core.models import Project, Run, RunStatus, Stage, TaskStatus

from .artifact_service import ArtifactSnapshotService
from .plan_schema import Plan
from .task_service import TaskService
from .errors import InvalidRunTransitionError, RunNotFoundError


class InMemoryRunStore:
    def __init__(self) -> None:
        self._runs_by_id: Dict[str, Run] = {}
        self._runs_by_project: Dict[str, List[str]] = {}

    def add(self, run: Run) -> None:
        self._runs_by_id[run.run_id] = run
        self._runs_by_project.setdefault(run.project_id, []).append(run.run_id)

    def get(self, run_id: str) -> Run:
        run = self._runs_by_id.get(run_id)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} not found")
        return run

    def update(self, run: Run) -> None:
        if run.run_id not in self._runs_by_id:
            raise RunNotFoundError(f"Run {run.run_id} not found")
        self._runs_by_id[run.run_id] = run

    def list_by_project(self, project_id: str) -> List[Run]:
        run_ids = self._runs_by_project.get(project_id, [])
        return [self._runs_by_id[run_id] for run_id in run_ids]


class RunService:
    _ALLOWED_TRANSITIONS: Dict[RunStatus, Set[RunStatus]] = {
        RunStatus.PENDING: {RunStatus.RUNNING},
        RunStatus.RUNNING: {
            RunStatus.PAUSED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELED,
        },
        RunStatus.PAUSED: {RunStatus.RUNNING},
        RunStatus.COMPLETED: set(),
        RunStatus.FAILED: set(),
        RunStatus.CANCELED: set(),
    }

    def __init__(
        self,
        store: InMemoryRunStore,
        ledger: ActionLedger,
        agent_registry: Optional[AgentRegistry] = None,
        project_getter: Optional[Callable[[str], Project]] = None,
        artifact_service: Optional[ArtifactSnapshotService] = None,
        task_service: Optional[TaskService] = None,
        docs_root: Optional[Path] = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._agent_registry = agent_registry
        self._project_getter = project_getter
        self._artifact_service = artifact_service
        self._task_service = task_service
        self._docs_root = docs_root or self._resolve_docs_root()

    def create_run(self, project_id: str, stage: Stage) -> Run:
        run = Run(
            run_id=str(uuid4()),
            project_id=project_id,
            stage=stage,
            status=RunStatus.PENDING,
            started_at=None,
            finished_at=None,
        )
        self._store.add(run)
        self._ledger.log(
            run_id=run.run_id,
            project_id=run.project_id,
            stage=run.stage,
            agent_name="system",
            tool_name="run_service",
            message="Run created",
            details={"status": run.status.value},
        )
        return run

    def list_runs(self, project_id: str) -> List[Run]:
        return self._store.list_by_project(project_id)

    def list_tasks(self, run_id: str):
        if self._task_service is None:
            raise ValueError("Task service not configured")
        self._store.get(run_id)
        return self._task_service.list_tasks(run_id)

    def get_run(self, run_id: str) -> Run:
        return self._store.get(run_id)

    def start_run(self, run_id: str) -> Run:
        run = self._store.get(run_id)
        if self._artifact_service is not None:
            self._artifact_service.assert_not_stale(run.project_id, run.stage)
        run = self._transition(run_id, RunStatus.RUNNING, "Run started")

        if self._agent_registry and run.stage == Stage.REQUIREMENTS_DRAFTED:
            project = self._project_or_none(run.project_id)
            context = ExecutionContext(
                project=project,
                run=run,
                task=None,
                stage=run.stage,
                artifacts={},
                approvals={},
                constraints={},
                registry={
                    "docs_root": self._docs_root,
                    "should_continue": lambda: self._store.get(run.run_id).status
                    == RunStatus.RUNNING,
                },
                logger=self._ledger,
            )
            try:
                agent = self._agent_registry.get(AgentType.REQUIREMENTS, run.stage)
                agent.run(context)
            except Exception as exc:
                self._ledger.log(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    stage=run.stage,
                    agent_name="requirements_agent",
                    tool_name="run_service",
                    message="Requirements agent error",
                    details={"error": str(exc)},
                )
                return self.fail_run(run.run_id, reason=str(exc))

        if self._agent_registry and run.stage == Stage.DESIGN_DRAFTED:
            project = self._project_or_none(run.project_id)
            context = ExecutionContext(
                project=project,
                run=run,
                task=None,
                stage=run.stage,
                artifacts={},
                approvals={},
                constraints={"max_parallel_tasks": 2},
                registry={
                    "docs_root": self._docs_root,
                    "should_continue": lambda: self._store.get(run.run_id).status
                    == RunStatus.RUNNING,
                },
                logger=self._ledger,
            )
            try:
                agent = self._agent_registry.get(AgentType.PLANNER, run.stage)
                result: AgentResult = agent.run(context)
                plan_path = result.output if result.output is not None else self._docs_root / "PLAN.json"
                plan = Plan.model_validate_json(Path(plan_path).read_text())
                if self._task_service is not None:
                    tasks = self._task_service.create_tasks_from_plan(run.run_id, plan)
                    self._ledger.log(
                        run_id=run.run_id,
                        project_id=run.project_id,
                        stage=run.stage,
                        agent_name="planner_agent",
                        tool_name="task_service",
                        message="Created agent tasks from PLAN.json",
                        details={"task_ids": [task.task_id for task in tasks]},
                    )
            except Exception as exc:
                self._ledger.log(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    stage=run.stage,
                    agent_name="planner_agent",
                    tool_name="run_service",
                    message="Planner agent error",
                    details={"error": str(exc)},
                )
                return self.fail_run(run.run_id, reason=str(exc))

        return run

    def execute_tasks_bounded(self, run_id: str, max_parallel_tasks: int = 2) -> None:
        if self._task_service is None:
            raise ValueError("Task service not configured")
        run = self._store.get(run_id)
        if run.status != RunStatus.RUNNING:
            raise ValueError("Run must be RUNNING to execute tasks")

        while True:
            if self._store.get(run_id).status != RunStatus.RUNNING:
                self._ledger.log(
                    run_id=run_id,
                    project_id=run.project_id,
                    stage=run.stage,
                    agent_name="system",
                    tool_name="task_executor",
                    message="Task execution halted (run not RUNNING)",
                )
                return

            tasks = self._task_service.list_tasks(run_id)
            pending = [task for task in tasks if task.status == TaskStatus.PENDING]
            if not pending:
                return

            ready = [task for task in pending if self._deps_done(task, tasks)]
            if not ready:
                return

            selected = self._select_ready_batch(ready, max_parallel_tasks)
            for task in selected:
                if self._store.get(run_id).status != RunStatus.RUNNING:
                    return
                context = ExecutionContext(
                    project=self._project_or_none(run.project_id),
                    run=run,
                    task=task,
                    stage=run.stage,
                    artifacts={},
                    approvals={},
                    constraints={"max_parallel_tasks": max_parallel_tasks},
                    registry={"docs_root": self._docs_root},
                    logger=self._ledger,
                )
                self._execute_task(context)

                if task.status == TaskStatus.FAILED:
                    self.fail_run(run_id, reason=f"Task {task.task_id} failed")
                    return

    def pause_run(self, run_id: str) -> Run:
        return self._transition(run_id, RunStatus.PAUSED, "Run paused")

    def resume_run(self, run_id: str) -> Run:
        return self._transition(run_id, RunStatus.RUNNING, "Run resumed")

    def complete_run(self, run_id: str) -> Run:
        return self._transition(run_id, RunStatus.COMPLETED, "Run completed")

    def fail_run(self, run_id: str, reason: str | None = None) -> Run:
        message = "Run failed" if reason is None else f"Run failed: {reason}"
        return self._transition(
            run_id,
            RunStatus.FAILED,
            message,
            details={"reason": reason} if reason else None,
        )

    def cancel_run(self, run_id: str) -> Run:
        return self._transition(run_id, RunStatus.CANCELED, "Run canceled")

    def _transition(
        self,
        run_id: str,
        to_status: RunStatus,
        message: str,
        details: dict | None = None,
    ) -> Run:
        run = self._store.get(run_id)
        current_status = run.status
        allowed = self._ALLOWED_TRANSITIONS.get(current_status, set())
        if to_status not in allowed:
            raise InvalidRunTransitionError(
                f"Invalid run transition {current_status.value} -> {to_status.value}"
            )

        if to_status == RunStatus.RUNNING and run.started_at is None:
            run.started_at = datetime.utcnow()
        if to_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELED}:
            run.finished_at = datetime.utcnow()

        run.status = to_status
        self._store.update(run)

        self._ledger.log(
            run_id=run.run_id,
            project_id=run.project_id,
            stage=run.stage,
            agent_name="system",
            tool_name="run_service",
            message=message,
            details={
                "from": current_status.value,
                "to": to_status.value,
                **({"context": details} if details else {}),
            },
        )
        return run

    def _execute_task(self, context: ExecutionContext) -> None:
        task = context.task
        run = context.run
        if task is None or run is None:
            return
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        self._task_service.update_task(task)
        if context.logger:
            context.logger.log(
                run_id=run.run_id,
                project_id=run.project_id,
                stage=run.stage,
                agent_name=task.agent,
                tool_name="task_executor",
                message=f"Task {task.task_id} started",
                details={"task_id": task.task_id},
            )

        try:
            for output in task.outputs:
                output_path = (
                    self._docs_root.parent / output
                    if output.startswith("docs/")
                    else self._docs_root / output
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    f"# {task.title}\n\nGenerated by {task.agent}.\n"
                )
                if context.logger:
                    context.logger.log(
                        run_id=run.run_id,
                        project_id=run.project_id,
                        stage=run.stage,
                        agent_name=task.agent,
                        tool_name="file_write",
                        message=f"Wrote {output}",
                        details={"task_id": task.task_id, "path": str(output_path)},
                    )
            task.status = TaskStatus.DONE
            task.finished_at = datetime.utcnow()
            self._task_service.update_task(task)
            if context.logger:
                context.logger.log(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    stage=run.stage,
                    agent_name=task.agent,
                    tool_name="task_executor",
                    message=f"Task {task.task_id} completed",
                    details={"task_id": task.task_id},
                )
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            task.finished_at = datetime.utcnow()
            self._task_service.update_task(task)
            if context.logger:
                context.logger.log(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    stage=run.stage,
                    agent_name=task.agent,
                    tool_name="task_executor",
                    message=f"Task {task.task_id} failed",
                    details={"task_id": task.task_id, "error": str(exc)},
                )

    @staticmethod
    def _deps_done(task, tasks) -> bool:
        if not task.depends_on:
            return True
        status_by_id = {record.task_id: record.status for record in tasks}
        return all(status_by_id.get(dep) == TaskStatus.DONE for dep in task.depends_on)

    @staticmethod
    def _select_ready_batch(tasks, max_parallel_tasks: int):
        tasks_sorted = sorted(tasks, key=lambda t: (t.parallel_group, t.task_id))
        if not tasks_sorted:
            return []
        min_group = tasks_sorted[0].parallel_group
        group_tasks = [task for task in tasks_sorted if task.parallel_group == min_group]
        return group_tasks[: max_parallel_tasks]

    @staticmethod
    def _resolve_docs_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "docs").exists() and (parent / "apps").exists():
                return parent / "docs"
        return Path.cwd() / "docs"

    def _project_or_none(self, project_id: str) -> Optional[Project]:
        if self._project_getter is None:
            return None
        try:
            return self._project_getter(project_id)
        except Exception:
            return None
