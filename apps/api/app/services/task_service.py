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

    def sync_tasks_from_plan(self, run_id: str, plan: Plan) -> List[AgentTask]:
        now = datetime.utcnow()
        existing = {t.task_id: t for t in self._store.list_by_run(run_id)}
        reused = set(plan.reused_task_ids or [])
        regenerated = set(plan.regenerated_task_ids or [])
        new_records: List[AgentTask] = []

        for task in plan.tasks:
            prev = existing.get(task.task_id)
            if task.task_id in reused and prev:
                # preserve existing task, update metadata
                prev.plan_id = plan.plan_id
                prev.plan_version = plan.plan_version or prev.plan_version
                prev.deprecated = False
                prev.superseded_by = None
                self._store.update(prev)
                new_records.append(prev)
                continue

            record = AgentTask(
                task_id=task.task_id,
                run_id=run_id,
                agent=task.agent,
                title=task.title,
                status=TaskStatus.PENDING,
                depends_on=list(task.depends_on),
                parallel_group=task.parallel_group,
                outputs=list(task.outputs),
                linked_requirements=list(task.linked_requirements),
                plan_id=plan.plan_id,
                plan_version=plan.plan_version or 1,
                parent_task_id=prev.task_id if prev else None,
                created_at=now,
            )
            if prev:
                prev.deprecated = True
                prev.superseded_by = record.task_id
                self._store.update(prev)
            self._store.add(record)
            new_records.append(record)

        # mark removed tasks as deprecated
        plan_task_ids = {t.task_id for t in plan.tasks}
        for tid, t in existing.items():
            if tid not in plan_task_ids:
                t.deprecated = True
                self._store.update(t)

        return self._store.list_by_run(run_id)

    def list_tasks(self, run_id: str) -> List[AgentTask]:
        return self._store.list_by_run(run_id)

    def update_task(self, task: AgentTask) -> None:
        self._store.update(task)
