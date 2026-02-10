from __future__ import annotations

from statistics import mean
from typing import Dict, Optional

from core.models import ChangeStatus, RunStatus, TaskStatus

from .artifact_service import ArtifactSnapshotService
from .change_service import ChangeRequestService
from .run_service import RunService


class MetricsService:
    def __init__(
        self,
        run_service: RunService,
        artifact_service: ArtifactSnapshotService,
        change_service: ChangeRequestService,
    ) -> None:
        self._run_service = run_service
        self._artifact_service = artifact_service
        self._change_service = change_service

    def get_project_metrics(self, project_id: str) -> Dict[str, int]:
        runs = self._run_service.list_runs(project_id)
        total_runs = len(runs)
        active_runs = sum(
            1
            for run in runs
            if run.status in {RunStatus.RUNNING, RunStatus.PAUSED}
        )
        stale_count = len(self._artifact_service.get_stale_stages(project_id))
        changes = self._change_service.list_for_project(project_id)
        open_changes = sum(1 for change in changes if change.status == ChangeStatus.OPEN)
        return {
            "total_runs": total_runs,
            "active_runs": active_runs,
            "stale_count": stale_count,
            "open_changes": open_changes,
        }

    def get_run_metrics(self, run_id: str) -> Dict[str, object]:
        run = self._run_service.get_run(run_id)
        try:
            tasks = self._run_service.list_tasks(run_id)
        except ValueError:
            tasks = []

        counts = {
            TaskStatus.PENDING: 0,
            TaskStatus.RUNNING: 0,
            TaskStatus.DONE: 0,
            TaskStatus.FAILED: 0,
            TaskStatus.CANCELED: 0,
        }
        agent_distribution: Dict[str, int] = {}
        durations = []

        for task in tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
            agent_distribution[task.agent] = agent_distribution.get(task.agent, 0) + 1
            if task.started_at and task.finished_at:
                durations.append((task.finished_at - task.started_at).total_seconds())

        duration_seconds: Optional[float] = None
        if run.started_at and run.finished_at:
            duration_seconds = (run.finished_at - run.started_at).total_seconds()

        avg_task_duration = mean(durations) if durations else None

        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_seconds": duration_seconds,
            "tasks_total": len(tasks),
            "tasks_pending": counts[TaskStatus.PENDING],
            "tasks_running": counts[TaskStatus.RUNNING],
            "tasks_done": counts[TaskStatus.DONE],
            "tasks_failed": counts[TaskStatus.FAILED],
            "tasks_canceled": counts[TaskStatus.CANCELED],
            "avg_task_duration_seconds": avg_task_duration,
            "retries": 0,
            "agent_distribution": agent_distribution,
        }
