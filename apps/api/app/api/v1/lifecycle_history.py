from __future__ import annotations

import uuid
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ActivityLog
from app.db.session import get_session

router = APIRouter(prefix="/store", tags=["lifecycle"])


@router.get("/projects/{project_id}/lifecycle-score-history")
async def lifecycle_score_history(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> List[dict[str, Any]]:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await session.execute(
        select(ActivityLog)
        .where(
            ActivityLog.project_id == project_id,
            ActivityLog.action_type == "lifecycle.score",
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(50)
    )
    logs = result.scalars().all()
    return [
        {
            "timestamp": log.created_at,
            "score": log.extra_metadata.get("health_index") if log.extra_metadata else None,
            "grade": log.extra_metadata.get("grade") if log.extra_metadata else None,
            "risk_level": log.extra_metadata.get("risk_level") if log.extra_metadata else None,
            "structural": log.extra_metadata.get("structural_score") if log.extra_metadata else None,
            "stability": log.extra_metadata.get("stability_score") if log.extra_metadata else None,
            "confidence": log.extra_metadata.get("confidence_score") if log.extra_metadata else None,
            "governance": log.extra_metadata.get("governance_score") if log.extra_metadata else None,
            "warnings": log.extra_metadata.get("warnings") if log.extra_metadata else None,
        }
        for log in logs
    ]
