from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.mission_control import (
    MissionControlMemoryExplainResponse,
    MissionControlProjectUnderstandingResponse,
    MissionControlMemorySummaryListResponse,
    MissionControlExecutionConsoleResponse,
    MissionControlOverviewResponse,
    MissionControlTimelineBackfillResponse,
    MissionControlTimelineResponse,
)
from app.services.memory_synthesizer import synthesize_project_memory, synthesize_project_understanding
from app.services.mission_control_overview import build_mission_control_overview
from app.services.project_evolution_timeline import (
    build_project_evolution_timeline,
    count_persisted_timeline_events,
    explain_memory_event_chain,
    list_memory_summaries,
    materialize_timeline_summaries,
)
from app.services.run_execution_console import build_run_execution_console

public_router = APIRouter(tags=["mission-control"])
_OVERVIEW_CACHE_TTL_SECONDS = 2.0
_OVERVIEW_CACHE: dict[tuple[uuid.UUID, uuid.UUID, bool], tuple[float, MissionControlOverviewResponse]] = {}


@public_router.get("/projects/{project_id}/mission-control/overview", response_model=MissionControlOverviewResponse)
async def mission_control_overview(
    project_id: uuid.UUID,
    include_heavy: bool = False,
    force_refresh: bool = False,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlOverviewResponse:
    cache_key = (ctx.tenant_id, project_id, include_heavy)
    if not include_heavy and not force_refresh:
        cached = _OVERVIEW_CACHE.get(cache_key)
        if cached is not None:
            cached_at, payload = cached
            if (time.monotonic() - cached_at) < _OVERVIEW_CACHE_TTL_SECONDS:
                return payload
    try:
        payload = await build_mission_control_overview(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            lightweight=not include_heavy,
        )
        if not include_heavy:
            _OVERVIEW_CACHE[cache_key] = (time.monotonic(), payload)
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@public_router.get("/runs/{run_id}/execution-console", response_model=MissionControlExecutionConsoleResponse)
async def mission_control_execution_console(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlExecutionConsoleResponse:
    try:
        return await build_run_execution_console(
            session,
            tenant_id=ctx.tenant_id,
            run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@public_router.get("/projects/{project_id}/memory/timeline", response_model=MissionControlTimelineResponse)
async def project_memory_timeline(
    project_id: uuid.UUID,
    limit: int = 60,
    domain: str | None = None,
    severity: str | None = None,
    requirement_id: str | None = None,
    run_id: uuid.UUID | None = None,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlTimelineResponse:
    try:
        return await build_project_evolution_timeline(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            limit=max(10, min(limit, 200)),
            domain=(domain or "").strip().lower() or None,
            severity=(severity or "").strip().lower() or None,
            requirement_id=(requirement_id or "").strip() or None,
            run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@public_router.post("/projects/{project_id}/memory/timeline/backfill", response_model=MissionControlTimelineBackfillResponse)
async def backfill_project_memory_timeline(
    project_id: uuid.UUID,
    limit: int = 200,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlTimelineBackfillResponse:
    bounded_limit = max(40, min(limit, 500))
    try:
        before_count = await count_persisted_timeline_events(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
        await build_project_evolution_timeline(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            limit=bounded_limit,
        )
        await materialize_timeline_summaries(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
        after_count = await count_persisted_timeline_events(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
        return MissionControlTimelineBackfillResponse(
            project_id=project_id,
            scanned_limit=bounded_limit,
            before_count=before_count,
            after_count=after_count,
            inserted_count=max(0, after_count - before_count),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@public_router.get("/projects/{project_id}/memory/summaries", response_model=MissionControlMemorySummaryListResponse)
async def project_memory_summaries(
    project_id: uuid.UUID,
    summary_type: str | None = None,
    limit: int = 30,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlMemorySummaryListResponse:
    return await list_memory_summaries(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        summary_type=(summary_type or "").strip() or None,
        limit=max(1, min(limit, 100)),
    )


@public_router.post("/projects/{project_id}/memory/summaries/materialize", response_model=MissionControlMemorySummaryListResponse)
async def materialize_project_memory_summaries(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlMemorySummaryListResponse:
    return await synthesize_project_memory(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
    )


@public_router.get("/projects/{project_id}/memory/explain", response_model=MissionControlMemoryExplainResponse)
async def explain_project_memory(
    project_id: uuid.UUID,
    requirement_id: str | None = None,
    run_id: uuid.UUID | None = None,
    limit: int = 20,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlMemoryExplainResponse:
    return await explain_memory_event_chain(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        requirement_id=(requirement_id or "").strip() or None,
        run_id=run_id,
        limit=max(5, min(limit, 100)),
    )


@public_router.get("/projects/{project_id}/memory/project-understanding", response_model=MissionControlProjectUnderstandingResponse)
async def project_understanding_memory(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlProjectUnderstandingResponse:
    payload = await synthesize_project_understanding(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
    )
    return MissionControlProjectUnderstandingResponse(**payload)
