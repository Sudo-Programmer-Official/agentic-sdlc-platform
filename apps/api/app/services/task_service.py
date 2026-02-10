from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from core.models import AgentTask, TaskStatus

from .plan_schema import Plan


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._tasks_by_id: Dict[str, AgentTask] = {}
        self._tasks_by_run: Dict[str, List[str]] = {}

    def add(self, task: AgentTask) -> None:
        self._tasks_by_id[task.task_id] = task
        self._tasks_by_run.setdefault(task.run_id, []).append(task.task_id)

    def get(self, task_id: str) -> AgentTask:
        return self._tasks_by_id[task_id]

    def update(self, task: AgentTask) -> None:
        self._tasks_by_id[task.task_id] = task

    def list_by_run(self, run_id: str) -> List[AgentTask]:
        task_ids = self._tasks_by_run.get(run_id, [])
        return [self._tasks_by_id[task_id] for task_id in task_ids]


class TaskService:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self._store = store

    def create_tasks_from_plan(self, run_id: str, plan: Plan) -> List[AgentTask]:
        tasks: List[AgentTask] = []
        now = datetime.utcnow()
        for task in plan.tasks:
            record = AgentTask(
                task_id=task.task_id,
                run_id=run_id,
                agent=task.agent,
                title=task.title,
                status=TaskStatus.PENDING,
                depends_on=list(task.depends_on),
                parallel_group=task.parallel_group,
                outputs=list(task.outputs),
                created_at=now,
            )
            self._store.add(record)
            tasks.append(record)
        return tasks

    def list_tasks(self, run_id: str) -> List[AgentTask]:
        return self._store.list_by_run(run_id)

    def update_task(self, task: AgentTask) -> None:
        self._store.update(task)
