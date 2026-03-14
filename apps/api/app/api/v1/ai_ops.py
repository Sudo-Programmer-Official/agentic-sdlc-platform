from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.ai_ops import AIOpsDashboardOut
from app.services.ai_policy import AIJobManager


router = APIRouter(prefix="/ai/ops", tags=["ai-ops"])


@router.get("/dashboard", response_model=AIOpsDashboardOut)
async def ai_ops_dashboard(
    project_id: uuid.UUID | None = Query(default=None),
    repository_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> AIOpsDashboardOut:
    manager = AIJobManager.from_session(session)
    payload = await manager.get_dashboard(project_id=project_id, repository_id=repository_id, session=session)
    return AIOpsDashboardOut.model_validate(payload)
