from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.health import project_health
from app.db.models import Artifact, Run
from app.services.repo_map import build_project_repo_map, search_project_repo_map
from app.services.operator_tools import (
    compare_project_runs as _compare_project_runs,
    explain_artifact as _explain_artifact,
    get_current_project as _get_current_project,
    get_latest_run as _get_latest_run,
    get_run_by_id as _get_run_by_id,
    get_workspace_status as _get_workspace_status,
)


async def get_current_project(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
    return await _get_current_project(session, tenant_id=tenant_id, project_id=project_id)


async def get_latest_run(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
    return await _get_latest_run(session, tenant_id=tenant_id, project_id=project_id)


async def get_run_by_id(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    return await _get_run_by_id(session, tenant_id=tenant_id, project_id=project_id, run_id=run_id)


async def get_recent_artifacts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 5,
) -> list[dict[str, Any]]:
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.tenant_id == tenant_id,
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "artifact_id": str(artifact.id),
            "type": artifact.type,
            "uri": artifact.uri,
            "run_id": str(artifact.run_id) if artifact.run_id else None,
        }
        for artifact in artifacts
    ]


async def get_artifact_explanation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return await _explain_artifact(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        artifact_id=artifact_id,
    )


async def get_last_two_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[str]:
    runs = (
        await session.execute(
            select(Run.id)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(2)
        )
    ).scalars().all()
    return [str(run_id) for run_id in runs]


async def compare_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_a: uuid.UUID | None = None,
    run_b: uuid.UUID | None = None,
) -> dict[str, Any]:
    return await _compare_project_runs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        run_a_id=run_a,
        run_b_id=run_b,
    )


async def get_workspace_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return await _get_workspace_status(session, tenant_id=tenant_id, project_id=project_id, run_id=run_id)


async def get_project_health_summary(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    return await project_health(project_id, session)


async def get_repo_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 120,
) -> dict[str, Any]:
    result = await build_project_repo_map(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
    )
    return result.model_dump()


async def search_repo_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> dict[str, Any]:
    result = await search_project_repo_map(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        query=query,
        limit=limit,
    )
    return result.model_dump()
