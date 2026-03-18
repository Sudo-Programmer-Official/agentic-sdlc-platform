from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.mission_control import MissionControlExecutionConsoleResponse, MissionControlOverviewResponse
from app.services.mission_control_overview import build_mission_control_overview
from app.services.run_execution_console import build_run_execution_console

public_router = APIRouter(tags=["mission-control"])


@public_router.get("/projects/{project_id}/mission-control/overview", response_model=MissionControlOverviewResponse)
async def mission_control_overview(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> MissionControlOverviewResponse:
    try:
        return await build_mission_control_overview(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
        )
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
