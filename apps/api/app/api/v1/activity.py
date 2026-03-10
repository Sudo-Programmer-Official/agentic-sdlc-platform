from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ActivityLog
from app.api.deps import get_tenant_context
from app.db.session import get_session
from app.schemas.activity import ActivityOut

router = APIRouter(prefix="/store", tags=["activity"])


@router.get("/projects/{project_id}/activity", response_model=List[ActivityOut])
async def list_activity(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[ActivityOut]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.project_id == project_id, ActivityLog.tenant_id == ctx.tenant_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(50)
    )
    logs = result.scalars().all()
    data = []
    for l in logs:
        obj = ActivityOut.model_validate(l)
        if getattr(l, "extra_metadata", None):
            obj.metadata = l.extra_metadata
        data.append(obj)
    return data
