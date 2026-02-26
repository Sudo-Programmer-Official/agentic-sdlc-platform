from __future__ import annotations

import uuid
from typing import Any
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Trace, Approval, ActivityLog
from app.db.session import get_session
from app.api.v1.health import project_health
from app.services.activity_log import log_activity

# Keep legacy /store/... routes and add public /projects/... routes to match frontend calls.
router = APIRouter(prefix="/store", tags=["lifecycle"])
public_router = APIRouter(tags=["lifecycle"])


def grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


@router.get("/projects/{project_id}/lifecycle-score")
@public_router.get("/projects/{project_id}/lifecycle-score")
async def lifecycle_score(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Structural (from health counts)
    health = await project_health(project_id, session)
    counts = health.get("counts", {})
    structural_penalty = (
        counts.get("cycles", 0) * 10
        + counts.get("orphan_tasks", 0) * 2
        + counts.get("docs_without_tasks", 0) * 2
        + counts.get("tasks_without_trace", 0) * 3
        + counts.get("deprecated_without_supersede", 0) * 3
        + max(0, counts.get("longest_chain", 0) - 5) * 2
    )
    structural_score = max(0, 100 - structural_penalty)

    # Stability: regen frequency, force usage, supersede depth
    regen_count = await session.scalar(
        select(func.count()).select_from(
            select(Trace.id)
            .where(Trace.project_id == project_id, Trace.relation_type == "supersedes", Trace.deleted_at.is_(None))
            .subquery()
        )
    ) or 0
    force_regens = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.status == "DEPRECATED",
                Task.deleted_at.is_(None),
            )
            .subquery()
        )
    ) or 0
    supersede_depth = counts.get("longest_chain", 0)
    stability_penalty = regen_count * 1 + force_regens * 2 + max(0, supersede_depth - 5) * 2
    stability_score = max(0, 100 - stability_penalty)

    # Confidence: average confidence on traces with AI metadata
    conf_avg = await session.scalar(
        select(func.avg(Trace.confidence_score)).where(
            Trace.project_id == project_id,
            Trace.confidence_score.isnot(None),
            Trace.deleted_at.is_(None),
        )
    )
    confidence_score = int((conf_avg or 0.75) * 100)

    # Governance: approvals present on tasks?
    approvals_count = await session.scalar(
        select(func.count()).select_from(
            select(Approval.id)
            .where(Approval.project_id == project_id, Approval.deleted_at.is_(None))
            .subquery()
        )
    ) or 0
    open_approvals = await session.scalar(
        select(func.count()).select_from(
            select(Approval.id)
            .where(
                Approval.project_id == project_id,
                Approval.status == "PENDING",
                Approval.deleted_at.is_(None),
            )
            .subquery()
        )
    ) or 0
    governance_penalty = max(0, open_approvals - approvals_count * 0.5)
    governance_base = 100 if approvals_count else 80
    governance_score = max(0, governance_base - governance_penalty)

    # Weighted composite (Structural 40, Stability 30, Confidence 20, Governance 10)
    composite = (
        structural_score * 0.4
        + stability_score * 0.3
        + confidence_score * 0.2
        + governance_score * 0.1
    )
    health_index = round(composite, 2)

    warnings = []
    if counts.get("orphan_tasks", 0) > 0:
        warnings.append("Orphan tasks detected")
    if counts.get("cycles", 0) > 0:
        warnings.append("Cycles detected in trace graph")
    if regen_count > 10:
        warnings.append("Regeneration frequency elevated")
    if confidence_score < 70:
        warnings.append("Low confidence aggregate")

    result = {
        "health_index": health_index,
        "grade": grade(health_index),
        "risk_level": "LOW" if health_index >= 85 else "MEDIUM" if health_index >= 70 else "HIGH",
        "structural_score": structural_score,
        "stability_score": stability_score,
        "confidence_score": confidence_score,
        "governance_score": governance_score,
        "counts": counts,
        "regen_count": regen_count,
        "supersede_depth": supersede_depth,
        "warnings": warnings,
    }

    # Dedup logging: log only if score changed by >1 point or last log older than 10 minutes
    log = await session.execute(
        select(ActivityLog)
        .where(
            ActivityLog.project_id == project_id,
            ActivityLog.action_type == "lifecycle.score",
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(1)
    )
    last_log = log.scalars().first()
    should_log = True
    if last_log:
        last_score = last_log.extra_metadata.get("health_index") if last_log.extra_metadata else None
        last_time = last_log.created_at
        if last_score is not None and abs(last_score - health_index) <= 1 and last_time:
            # Normalise to aware datetimes to avoid naive/aware subtraction errors
            now = datetime.now(timezone.utc)
            last_ts = last_time if last_time.tzinfo else last_time.replace(tzinfo=timezone.utc)
            if now - last_ts < timedelta(minutes=10):
                should_log = False

    if should_log:
        async with session.begin():
            await log_activity(
                session,
                project_id=project_id,
                entity_type="project",
                entity_id=project_id,
                action_type="lifecycle.score",
                event_type="score",
                metadata=result,
            )

    return result
