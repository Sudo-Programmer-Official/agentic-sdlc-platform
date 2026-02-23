from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Artifact, Trace, Approval, ActivityLog
from app.db.session import get_session

router = APIRouter(prefix="/store", tags=["snapshot"])


@router.get("/projects/{project_id}/snapshot")
async def project_snapshot(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    docs = (await session.execute(select(Document).where(Document.project_id == project_id))).scalars().all()
    tasks = (await session.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    artifacts = (await session.execute(select(Artifact).where(Artifact.project_id == project_id))).scalars().all()
    approvals = (await session.execute(select(Approval).where(Approval.project_id == project_id))).scalars().all()
    traces = (await session.execute(select(Trace).where(Trace.project_id == project_id))).scalars().all()
    activity = (await session.execute(select(ActivityLog).where(ActivityLog.project_id == project_id))).scalars().all()

    def serialize(items):
        data = []
        for item in items:
            d = item.__dict__.copy()
            if "extra_metadata" in d:
                d["metadata"] = d.pop("extra_metadata")
            data.append(d)
        return data

    return {
        "project": project.__dict__,
        "documents": serialize(docs),
        "tasks": serialize(tasks),
        "artifacts": serialize(artifacts),
        "approvals": serialize(approvals),
        "traces": serialize(traces),
        "activity": serialize(activity),
    }
