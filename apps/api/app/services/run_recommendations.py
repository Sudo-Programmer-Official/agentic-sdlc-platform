from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Task


@dataclass
class RecommendationTask:
    task_id: str
    title: str
    reason: str
    status: str
    source_type: str
    confidence: float


def _foundation_order_key(task: Task) -> tuple[int, datetime]:
    title = str(task.title or "").strip().lower()
    order = [
        "initialize monorepo",
        "initialize frontend",
        "initialize backend",
        "initialize contracts",
        "initialize requirements",
        "initialize ci",
        "initialize deployment profile",
        "initialize telemetry",
        "validate foundation",
    ]
    for idx, key in enumerate(order):
        if key in title:
            return idx, task.created_at
    return 999, task.created_at


def _build_recommendation(
    *,
    task: Task,
    reason: str,
    confidence: float,
) -> RecommendationTask:
    return RecommendationTask(
        task_id=str(task.id),
        title=str(task.title or "Untitled task"),
        reason=reason,
        status=str(task.status or "PENDING"),
        source_type=str(task.source_type or "manual"),
        confidence=max(0.0, min(1.0, float(confidence))),
    )


def _derive_recommendation(
    *,
    tasks: list[Task],
    latest_run: Run | None,
) -> tuple[RecommendationTask | None, list[str], list[str]]:
    active_tasks = [task for task in tasks if str(task.status or "").upper() in {"PENDING", "RUNNING"}]
    blocked_tasks = [task for task in tasks if str(task.status or "").upper() in {"FAILED", "BLOCKED", "CANCELED"}]
    foundation_tasks = [task for task in active_tasks if str(task.source_type or "") == "genesis_setup"]
    feature_tasks = [task for task in active_tasks if str(task.source_type or "") == "requirement_propagation"]

    blocked_by: list[str] = []
    recovery_suggestions: list[str] = []

    if latest_run is not None:
        run_status = str(latest_run.status or "").upper()
        if run_status in {"RUNNING", "QUEUED", "PAUSED"}:
            blocked_by.append(f"active_run_{run_status.lower()}")
            recovery_suggestions.append("Finish or pause the active run before starting additional manual tasks.")

    if any(str(task.source_type or "") == "genesis_setup" for task in blocked_tasks):
        blocked_by.append("foundation_blocked")
        recovery_suggestions.append("Resolve failed foundation items before feature capabilities.")

    if foundation_tasks:
        next_foundation = sorted(foundation_tasks, key=_foundation_order_key)[0]
        if blocked_by:
            reason = "Foundation work is pending but there are active blockers. Resolve blockers, then continue in foundation order."
            confidence = 0.68
        else:
            reason = "Foundation tasks must complete before feature capabilities to avoid downstream runtime drift."
            confidence = 0.9
        return _build_recommendation(task=next_foundation, reason=reason, confidence=confidence), blocked_by, recovery_suggestions

    if feature_tasks:
        feature_sorted = sorted(
            feature_tasks,
            key=lambda task: (
                0 if str(task.capability_id or "").strip().upper() == "CAP-001" else 1,
                task.created_at,
            ),
        )
        next_feature = feature_sorted[0]
        reason = "Foundation queue is clear; start feature implementation from the first capability slice."
        confidence = 0.84 if not blocked_by else 0.66
        return _build_recommendation(task=next_feature, reason=reason, confidence=confidence), blocked_by, recovery_suggestions

    if blocked_tasks:
        newest_blocked = sorted(blocked_tasks, key=lambda task: task.updated_at or task.created_at, reverse=True)[0]
        reason = "No runnable tasks remain. Resolve latest blocked/failed item or force rerun after preflight."
        return _build_recommendation(task=newest_blocked, reason=reason, confidence=0.56), blocked_by, recovery_suggestions

    return None, blocked_by, recovery_suggestions


async def get_run_recommendations(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    tasks = (
        await session.execute(
            select(Task)
            .where(Task.project_id == project_id, Task.tenant_id == tenant_id, Task.deleted_at.is_(None))
            .order_by(Task.updated_at.desc(), Task.created_at.desc())
        )
    ).scalars().all()
    latest_run = await session.scalar(
        select(Run)
        .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
        .order_by(Run.updated_at.desc(), Run.created_at.desc())
        .limit(1)
    )
    recommendation, blocked_by, recovery_suggestions = _derive_recommendation(tasks=tasks, latest_run=latest_run)
    return {
        "recommended_next_task": (
            {
                "task_id": recommendation.task_id,
                "title": recommendation.title,
                "reason": recommendation.reason,
                "status": recommendation.status,
                "source_type": recommendation.source_type,
                "confidence": recommendation.confidence,
            }
            if recommendation is not None
            else None
        ),
        "blocked_by": blocked_by,
        "recovery_suggestions": recovery_suggestions,
        "confidence": recommendation.confidence if recommendation is not None else 0.0,
        "reason_trace": [
            "foundation_first_ordering",
            "blocked_task_awareness",
            "active_run_awareness",
            "capability_priority_cap_001",
        ],
    }
