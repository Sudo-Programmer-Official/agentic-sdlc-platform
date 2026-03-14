from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Run, Task
from app.db.session import SessionLocal
from app.runtime.orchestrator import RunOrchestrator
from app.services.activity_log import log_activity
from app.services.event_log import record_event
from app.services.repo_connector import get_project_repository
from app.services.workspace_supervisor import ensure_run_workspace

log = logging.getLogger("app.run_launch")


def _build_task_run_summary(task: Task) -> dict[str, str | None]:
    title = task.title.strip()
    description = (task.description or "").strip() or None
    goal = title if not description else f"{title}: {description}"
    return {
        "goal": goal,
        "task_id": str(task.id),
        "task_title": title,
        "task_description": description,
        "task_source": task.source,
    }


def _schedule_orchestrator_start(
    orchestrator: RunOrchestrator,
    *,
    run_id: uuid.UUID,
    actor_type: str,
    actor_id: str | None,
    executor_name: str,
) -> None:
    task = asyncio.create_task(
        orchestrator.start(run_id, actor_type=actor_type, actor_id=actor_id, executor_name=executor_name)
    )

    def _log_result(completed: asyncio.Task[None]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            exc = completed.exception()
            if exc is not None:
                log.exception("Run orchestration failed run_id=%s", run_id, exc_info=exc)

    task.add_done_callback(_log_result)


async def launch_run_for_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    executor_name: str = "dummy",
    task_id: uuid.UUID | None = None,
    actor_type: str = "USER",
    actor_id: str | None = None,
    schedule: bool = True,
) -> Run:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")
    selected_task: Task | None = None
    run_summary: dict[str, str | None] | None = None
    if task_id is not None:
        selected_task = await session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.project_id == project_id,
                Task.tenant_id == tenant_id,
                Task.deleted_at.is_(None),
            )
        )
        if selected_task is None:
            raise ValueError("Task not found")
        run_summary = _build_task_run_summary(selected_task)

    existing_running = await session.scalar(
        select(func.count()).select_from(
            select(Run.id)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id, Run.status == "RUNNING")
            .subquery()
        )
    ) or 0
    if existing_running > 0:
        raise ValueError(
            "A run is already in progress for this project; finish or cancel it before starting another."
        )

    project_repo = await get_project_repository(session, project_id=project_id, tenant_id=tenant_id)
    run = Run(
        project_id=project_id,
        tenant_id=tenant_id,
        status="QUEUED",
        executor=executor_name.lower(),
        summary=run_summary,
    )
    session.add(run)
    await session.flush()
    if selected_task is not None:
        selected_task.run_id = run.id
        session.add(selected_task)
    await ensure_run_workspace(
        session,
        run,
        require_repo=run.executor in {"codex", "test"},
        repo_url=project_repo.repo_url if project_repo else None,
        repo_branch=project_repo.default_branch if project_repo else None,
        repo_provider=project_repo.provider if project_repo else None,
        repo_full_name=project_repo.repo_full_name if project_repo else None,
        repo_installation_id=project_repo.installation_id if project_repo else None,
    )
    await log_activity(
        session,
        project_id=project_id,
        entity_type="run",
        entity_id=run.id,
        action_type="run.created",
        metadata={
            "status": run.status,
            "executor": run.executor,
            "task_id": str(selected_task.id) if selected_task else None,
            "task_title": selected_task.title if selected_task else None,
        },
        actor=actor_id,
    )
    if selected_task is not None:
        await log_activity(
            session,
            project_id=project_id,
            entity_type="task",
            entity_id=selected_task.id,
            action_type="task.run.created",
            metadata={"run_id": str(run.id), "executor": run.executor, "status": run.status},
            actor=actor_id,
        )
    await record_event(
        session,
        project_id=project_id,
        run_id=run.id,
        event_type="RUN_CREATED",
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=tenant_id,
        task_id=selected_task.id if selected_task else None,
        payload={
            "status": run.status,
            "executor": run.executor,
            "task_id": str(selected_task.id) if selected_task else None,
            "task_title": selected_task.title if selected_task else None,
        },
    )
    log.info(
        "Run created project_id=%s run_id=%s executor=%s task_id=%s",
        project_id,
        run.id,
        run.executor,
        selected_task.id if selected_task else None,
    )
    await session.commit()
    await session.refresh(run)

    bind = session.get_bind()
    is_sqlite = bind is not None and bind.dialect.name == "sqlite"

    if schedule:
        orchestrator = RunOrchestrator(SessionLocal, executor_name=run.executor)
        try:
            await orchestrator.bootstrap_in_session(
                session,
                run.id,
                actor_type=actor_type,
                actor_id=actor_id,
                executor_name=run.executor,
            )
        except Exception:
            log.exception("Run bootstrap failed run_id=%s project_id=%s", run.id, run.project_id)
            raise
        await session.refresh(run)
        if not is_sqlite:
            _schedule_orchestrator_start(
                orchestrator,
                run_id=run.id,
                actor_type=actor_type,
                actor_id=actor_id,
                executor_name=run.executor,
            )
        else:
            log.info(
                "Run execution handoff deferred run_id=%s project_id=%s reason=sqlite_test_session",
                run.id,
                run.project_id,
            )

    return run
