from __future__ import annotations

import uuid
from typing import Any
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Trace, Approval, ActivityLog, Run
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

    # Empty-state short-circuit: no docs, no tasks, no traces → return neutral payload, no logging
    docs_count = await session.scalar(
        select(func.count()).select_from(
            select(Document.id)
            .where(Document.project_id == project_id, Document.deleted_at.is_(None))
            .subquery()
        )
    ) or 0
    tasks_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(Task.project_id == project_id, Task.deleted_at.is_(None))
            .subquery()
        )
    ) or 0
    traces_count = await session.scalar(
        select(func.count()).select_from(
            select(Trace.id)
            .where(Trace.project_id == project_id, Trace.deleted_at.is_(None))
            .subquery()
        )
    ) or 0
    if docs_count == 0 and tasks_count == 0 and traces_count == 0:
        return {
            "health_index": None,
            "grade": None,
            "risk_level": "UNKNOWN",
            "structural_score": None,
            "execution_score": None,
            "stability_score": None,
            "governance_score": None,
            "coverage_score": None,
            "confidence_score": None,
            "counts": counts,
            "execution": {},
            "stability": {},
            "coverage": {},
            "regen_count": 0,
            "supersede_depth": 0,
            "warnings": ["No documents, tasks, or traces yet; generate requirements and tasks first."],
        }
    # Structural score (reuse health counts)
    structural_penalty = (
        counts.get("cycles", 0) * 10
        + counts.get("orphan_tasks", 0) * 2
        + counts.get("docs_without_tasks", 0) * 2
        + counts.get("tasks_without_trace", 0) * 3
        + counts.get("deprecated_without_supersede", 0) * 3
        + max(0, counts.get("longest_chain", 0) - 5) * 2
    )
    structural_score = max(0, 100 - structural_penalty)

    # Regeneration/supersede depth (keep legacy fields for UI)
    regen_count = await session.scalar(
        select(func.count()).select_from(
            select(Trace.id)
            .where(
                Trace.project_id == project_id,
                Trace.relation_type == "supersedes",
                Trace.deleted_at.is_(None),
            )
            .subquery()
        )
    ) or 0

    # Coverage: traces attached to tasks
    tasks_with_trace = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.deleted_at.is_(None),
                exists().where(
                    Trace.project_id == project_id,
                    Trace.to_id == Task.id,
                    Trace.to_type == "task",
                    Trace.deleted_at.is_(None),
                ),
            )
            .subquery()
        )
    ) or 0
    if tasks_count > 0:
        coverage_ratio = tasks_with_trace / tasks_count
        coverage_score = int(coverage_ratio * 100)
    else:
        coverage_ratio = 0.0
        coverage_score = 30 if docs_count > 0 else 50

    # Governance: approvals
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
    governance_base = 100 if approvals_count else 80
    governance_penalty = min(40, open_approvals * 10)
    governance_score = max(0, governance_base - governance_penalty)

    # Runs: execution & stability
    runs_counts = await session.execute(
        select(
            func.count(),
            func.count().filter(Run.status == "COMPLETED"),
            func.count().filter(Run.status == "FAILED"),
            func.count().filter(Run.status == "CANCELED"),
            func.count().filter(Run.status == "RUNNING"),
        ).where(Run.project_id == project_id)
    )
    total_runs, completed_runs, failed_runs, canceled_runs, running_runs = runs_counts.first()

    # Durations for completed runs
    completed_rows = (
        await session.execute(
            select(Run.started_at, Run.finished_at).where(
                Run.project_id == project_id, Run.status == "COMPLETED", Run.started_at.isnot(None), Run.finished_at.isnot(None)
            )
        )
    ).all()
    durations: list[float] = []
    for start, finish in completed_rows:
        if start and finish:
            durations.append(max(0.0, (finish - start).total_seconds()))

    completion_ratio = completed_runs / total_runs if total_runs else 0.0
    failure_ratio = failed_runs / total_runs if total_runs else 0.0

    if total_runs == 0:
        execution_score = 50
        stability_score = 50
    else:
        running_penalty = 20 if running_runs > 0 else 0
        execution_score = int(max(0, 100 * completion_ratio - 30 * failure_ratio - running_penalty))
        if durations:
            avg_dur = sum(durations) / len(durations)
            if len(durations) > 1:
                mean = avg_dur
                variance = sum((d - mean) ** 2 for d in durations) / len(durations)
                std = variance ** 0.5
            else:
                std = 0.0
            ratio = min(1.0, std / avg_dur) if avg_dur > 0 else 1.0
            stability_score = int(max(0, 100 - ratio * 40))
        else:
            stability_score = 50

    execution = {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "canceled_runs": canceled_runs,
        "running_runs": running_runs,
        "completion_ratio": completion_ratio,
        "failure_ratio": failure_ratio,
        "avg_duration_seconds": (sum(durations) / len(durations)) if durations else None,
    }

    stability = {
        "avg_duration_seconds": (sum(durations) / len(durations)) if durations else None,
        "duration_std_seconds": None if not durations else (0.0 if len(durations) == 1 else (sum((d - (sum(durations)/len(durations))) ** 2 for d in durations) / len(durations)) ** 0.5),
        "duration_std_penalty": None,
        "churn_penalty_used": 0,
    }

    # Confidence score: completeness + run confidence
    real_dimensions = 1  # structural always present
    if total_runs > 0:
        real_dimensions += 1  # execution
    if durations:
        real_dimensions += 1  # stability
    if tasks_count > 0:
        real_dimensions += 1  # coverage
    real_dimensions += 1  # governance always present
    completeness = real_dimensions / 5
    run_confidence = completion_ratio if total_runs else 0.0
    confidence_score = int((0.6 * completeness + 0.4 * run_confidence) * 100)

    # Composite weights (Structural 30, Execution 30, Stability 20, Governance 10, Coverage 10)
    composite = (
        structural_score * 0.30
        + execution_score * 0.30
        + stability_score * 0.20
        + governance_score * 0.10
        + coverage_score * 0.10
    )
    health_index = round(composite, 2)

    # Warnings
    warnings = []
    if counts.get("orphan_tasks", 0) > 0:
        warnings.append("Orphan tasks detected")
    if counts.get("cycles", 0) > 0:
        warnings.append("Cycles detected in trace graph")
    if coverage_ratio < 0.70 and tasks_count > 0:
        warnings.append("Trace coverage below 70%")
    if failure_ratio > 0.30 and total_runs > 0:
        warnings.append("Run failure ratio above 30%")
    if running_runs > 0:
        warnings.append("There is an active run in progress")
    if completed_runs == 0 and total_runs == 0:
        warnings.append("No runs executed yet")

    result = {
        "health_index": health_index,
        "grade": grade(health_index),
        "risk_level": "LOW" if health_index >= 80 else "MEDIUM" if health_index >= 60 else "HIGH",
        "structural_score": structural_score,
        "execution_score": execution_score,
        "stability_score": stability_score,
        "governance_score": governance_score,
        "coverage_score": coverage_score,
        "confidence_score": confidence_score,
        "counts": counts,
        "execution": execution,
        "stability": stability,
        "coverage": {
            "total_tasks": tasks_count,
            "tasks_with_trace": tasks_with_trace,
            "coverage_ratio": coverage_ratio,
        },
        "regen_count": regen_count,
        "supersede_depth": counts.get("longest_chain", 0),
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
        async with session.begin_nested():
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
