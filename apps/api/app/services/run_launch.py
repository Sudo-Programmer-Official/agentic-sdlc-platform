from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Run
from app.db.session import SessionLocal
from app.runtime.orchestrator import RunOrchestrator
from app.services.activity_log import log_activity
from app.services.event_log import record_event
from app.services.repo_connector import get_project_repository
from app.services.workspace_supervisor import ensure_run_workspace


async def launch_run_for_project(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    executor_name: str = "dummy",
    actor_type: str = "USER",
    actor_id: str | None = None,
    schedule: bool = True,
) -> Run:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if project is None:
        raise ValueError("Project not found")

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
    run = Run(project_id=project_id, tenant_id=tenant_id, status="QUEUED", executor=executor_name.lower())
    session.add(run)
    await session.flush()
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
        metadata={"status": run.status, "executor": run.executor},
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
    )
    await session.commit()
    await session.refresh(run)

    bind = session.get_bind()
    should_schedule = schedule and not (bind is not None and bind.dialect.name == "sqlite")

    if should_schedule:
        orchestrator = RunOrchestrator(SessionLocal, executor_name=run.executor)
        asyncio.create_task(orchestrator.start(run.id, actor_type=actor_type, actor_id=actor_id, executor_name=run.executor))

    return run
