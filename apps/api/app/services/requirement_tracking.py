from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIJobRun, ImprovementRequest, Run, Task
from app.services.requirement_execution_graph import build_requirement_execution_graph
from app.services.requirement_intelligence import derive_requirement_intelligence
from app.services import requirements_service
from app.services.errors import RequirementGraphNotFoundError

ACTIVE_TASK_STATUSES = {"PENDING", "QUEUED", "RUNNING", "IN_PROGRESS"}
IN_PROGRESS_TASK_STATUSES = {"RUNNING", "IN_PROGRESS"}
COMPLETED_TASK_STATUSES = {"DONE", "COMPLETED", "CLOSED"}
FAILED_TASK_STATUSES = {"FAILED", "CANCELED", "BLOCKED"}

ACTIVE_RUN_STATUSES = {"QUEUED", "RUNNING"}
COMPLETED_RUN_STATUSES = {"COMPLETED"}
FAILED_RUN_STATUSES = {"FAILED", "CANCELED"}


def _normalize_req_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _task_requirement_ids(task: Task) -> list[str]:
    linked: list[str] = []
    if task.requirement_id:
        linked.append(task.requirement_id)
    if isinstance(task.derived_from_requirement_ids, list):
        linked.extend(str(item).strip() for item in task.derived_from_requirement_ids if str(item).strip())
    deduped = []
    seen: set[str] = set()
    for item in linked:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _run_requirement_ids(run: Run, *, tasks_by_id: dict[uuid.UUID, Task], tasks_by_run: dict[uuid.UUID, list[Task]]) -> list[str]:
    ids: list[str] = []
    summary = run.summary if isinstance(run.summary, dict) else {}

    req_id = _normalize_req_id(summary.get("requirement_id"))
    if req_id:
        ids.append(req_id)
    if isinstance(summary.get("requirement_ids"), list):
        ids.extend(str(item).strip() for item in summary.get("requirement_ids") if str(item).strip())

    task_ref = _normalize_req_id(summary.get("task_id"))
    if task_ref:
        try:
            task_uuid = uuid.UUID(task_ref)
            task = tasks_by_id.get(task_uuid)
            if task is not None:
                ids.extend(_task_requirement_ids(task))
        except ValueError:
            pass

    for task in tasks_by_run.get(run.id, []):
        ids.extend(_task_requirement_ids(task))

    out: list[str] = []
    seen: set[str] = set()
    for req in ids:
        if req in seen:
            continue
        seen.add(req)
        out.append(req)
    return out


def _build_requirement_seed(project_id: str) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    try:
        graph = requirements_service.get_graph(project_id)
    except RequirementGraphNotFoundError:
        return cards

    for node in getattr(graph, "nodes", []) or []:
        req_id = _normalize_req_id(getattr(node, "id", None))
        if not req_id:
            continue
        text = str(getattr(node, "text", "") or "").strip()
        title = text.split("\n", 1)[0][:160] if text else req_id
        cards[req_id] = {
            "requirement_id": req_id,
            "title": title,
            "priority": "MEDIUM",
            "created_at": getattr(graph, "created_at", None),
            "updated_at": getattr(graph, "updated_at", None),
        }
    return cards


def _status_engine(
    *,
    task_statuses: list[str],
    run_statuses: list[str],
    has_unresolved_improvement: bool,
    requirement_updated_at: datetime | None,
    latest_run_at: datetime | None,
    latest_run_status: str | None,
) -> str:
    if not task_statuses and not run_statuses:
        return "NOT_STARTED"
    if any(status in FAILED_RUN_STATUSES for status in run_statuses) and any(
        status in COMPLETED_RUN_STATUSES for status in run_statuses
    ):
        return "REGRESSION"
    if has_unresolved_improvement:
        return "NEEDS_REVIEW"
    if any(status in ACTIVE_TASK_STATUSES for status in task_statuses) or any(status in ACTIVE_RUN_STATUSES for status in run_statuses):
        return "IN_PROGRESS"
    if any(status in FAILED_TASK_STATUSES for status in task_statuses) and not any(
        status in COMPLETED_TASK_STATUSES for status in task_statuses
    ):
        return "BLOCKED"
    if latest_run_status in FAILED_RUN_STATUSES:
        return "FAILED"
    if any(status in FAILED_RUN_STATUSES for status in run_statuses) and not any(
        status in COMPLETED_RUN_STATUSES for status in run_statuses
    ):
        return "BLOCKED"
    if requirement_updated_at and latest_run_at and requirement_updated_at > latest_run_at:
        return "NEEDS_REVIEW"
    if task_statuses and all(status in COMPLETED_TASK_STATUSES for status in task_statuses):
        return "COMPLETE"
    if run_statuses and all(status in COMPLETED_RUN_STATUSES for status in run_statuses):
        return "COMPLETE"
    return "IN_PROGRESS"


def _health_engine(
    *,
    failed_tasks: int,
    failed_runs: int,
    unresolved_improvements: int,
    stale: bool,
    violation_count: int,
) -> tuple[int, str]:
    score = 100
    score -= failed_tasks * 10
    score -= failed_runs * 15
    score -= unresolved_improvements * 10
    if stale:
        score -= 5
    score -= min(violation_count, 4) * 5
    score = max(0, min(100, score))
    risk = "LOW" if score >= 75 else "MEDIUM" if score >= 50 else "HIGH"
    return score, risk


async def build_requirement_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    requirements = _build_requirement_seed(str(project_id))
    tasks = (
        await session.execute(
            select(Task).where(Task.tenant_id == tenant_id, Task.project_id == project_id, Task.deleted_at.is_(None))
        )
    ).scalars().all()
    tasks_by_id = {task.id: task for task in tasks}
    tasks_by_run: dict[uuid.UUID, list[Task]] = {}
    for task in tasks:
        if task.run_id:
            tasks_by_run.setdefault(task.run_id, []).append(task)
        for req in _task_requirement_ids(task):
            requirements.setdefault(req, {"requirement_id": req, "title": req, "priority": "MEDIUM"})

    runs = (
        await session.execute(select(Run).where(Run.tenant_id == tenant_id, Run.project_id == project_id))
    ).scalars().all()
    req_run_map: dict[str, list[Run]] = {}
    for run in runs:
        for req in _run_requirement_ids(run, tasks_by_id=tasks_by_id, tasks_by_run=tasks_by_run):
            req_run_map.setdefault(req, []).append(run)
            requirements.setdefault(req, {"requirement_id": req, "title": req, "priority": "MEDIUM"})

    improvements = (
        await session.execute(
            select(ImprovementRequest).where(ImprovementRequest.tenant_id == tenant_id, ImprovementRequest.project_id == project_id)
        )
    ).scalars().all()
    ai_jobs = (
        await session.execute(
            select(AIJobRun).where(
                AIJobRun.tenant_id == tenant_id,
                AIJobRun.project_id == project_id,
            )
        )
    ).scalars().all()
    ai_cost_by_run: dict[uuid.UUID, float] = {}
    ai_tokens_by_run: dict[uuid.UUID, int] = {}
    for job in ai_jobs:
        if not job.run_id:
            continue
        ai_cost_by_run[job.run_id] = ai_cost_by_run.get(job.run_id, 0.0) + float(
            job.actual_cost_cents or job.estimated_cost_cents or 0.0
        )
        ai_tokens_by_run[job.run_id] = ai_tokens_by_run.get(job.run_id, 0) + int(job.tokens_input or 0) + int(
            job.tokens_output or 0
        )
    improvements_by_req: dict[str, list[ImprovementRequest]] = {}
    runs_by_id = {run.id: run for run in runs}
    for request in improvements:
        source_run = runs_by_id.get(request.source_run_id)
        if source_run is None:
            continue
        req_ids = _run_requirement_ids(source_run, tasks_by_id=tasks_by_id, tasks_by_run=tasks_by_run)
        for req in req_ids:
            improvements_by_req.setdefault(req, []).append(request)

    cards: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for req_id, seed in requirements.items():
        graph_payload = await build_requirement_execution_graph(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            requirement_id=req_id,
        )
        req_tasks = graph_payload["tasks"]
        req_runs = graph_payload["runs"]
        req_improvements = graph_payload["improvements"]

        task_statuses = [str(task.status or "").upper() for task in req_tasks]
        run_statuses = [str(run.status or "").upper() for run in req_runs]

        run_timestamps = [
            _as_utc(ts)
            for ts in [
                max((run.updated_at or run.finished_at or run.started_at or run.created_at) for run in req_runs)
                if req_runs
                else None
            ]
            if ts
        ]
        latest_run_at = run_timestamps[0] if run_timestamps else None
        latest_run = max(
            req_runs,
            key=lambda run: run.updated_at or run.finished_at or run.started_at or run.created_at or datetime.min.replace(tzinfo=timezone.utc),
        ) if req_runs else None

        requirement_updated_at = _as_utc(seed.get("updated_at"))
        stale = bool(
            requirement_updated_at and (
                latest_run_at is None or (now - latest_run_at) > timedelta(days=14)
            )
        )

        unresolved_improvements = sum(1 for item in req_improvements if str(item.status or "").upper() not in {"COMPLETED", "DONE", "RESOLVED"})
        violation_count = 0
        for run in req_runs:
            summary = run.summary if isinstance(run.summary, dict) else {}
            records = summary.get("project_contract_violations")
            if isinstance(records, list):
                violation_count += len(records)

        status_value = _status_engine(
            task_statuses=task_statuses,
            run_statuses=run_statuses,
            has_unresolved_improvement=unresolved_improvements > 0,
            requirement_updated_at=requirement_updated_at,
            latest_run_at=latest_run_at,
            latest_run_status=str(latest_run.status).upper() if latest_run else None,
        )
        intelligence = derive_requirement_intelligence(
            requirement_updated_at=requirement_updated_at,
            tasks=req_tasks,
            runs=req_runs,
            improvements=req_improvements,
            related_files=graph_payload["related_files"],
            related_modules=graph_payload["related_modules"],
        )
        health_score, risk_level = _health_engine(
            failed_tasks=sum(1 for status in task_statuses if status in FAILED_TASK_STATUSES),
            failed_runs=sum(1 for status in run_statuses if status in FAILED_RUN_STATUSES),
            unresolved_improvements=unresolved_improvements,
            stale=stale,
            violation_count=violation_count,
        )

        last_activity_candidates = [_as_utc(seed.get("updated_at"))]
        last_activity_candidates.extend(_as_utc(task.updated_at) for task in req_tasks if task.updated_at)
        last_activity_candidates.extend(_as_utc(run.updated_at or run.finished_at or run.started_at) for run in req_runs)
        last_activity_candidates.extend(_as_utc(item.updated_at) for item in req_improvements if item.updated_at)
        last_activity_at = max((ts for ts in last_activity_candidates if ts is not None), default=None)

        cards.append(
            {
                "requirement_id": req_id,
                "title": seed.get("title") or req_id,
                "status": status_value,
                "priority": seed.get("priority") or "MEDIUM",
                "task_counts": {
                    "total": len(req_tasks),
                    "open": sum(1 for status in task_statuses if status in {"PENDING", "QUEUED"}),
                    "in_progress": sum(1 for status in task_statuses if status in IN_PROGRESS_TASK_STATUSES),
                    "completed": sum(1 for status in task_statuses if status in COMPLETED_TASK_STATUSES),
                    "failed": sum(1 for status in task_statuses if status in FAILED_TASK_STATUSES),
                    "rerun_pending": sum(1 for status in task_statuses if status in {"FAILED", "CANCELED"}),
                },
                "run_counts": {
                    "total": len(req_runs),
                    "running": sum(1 for status in run_statuses if status in ACTIVE_RUN_STATUSES),
                    "completed": sum(1 for status in run_statuses if status in COMPLETED_RUN_STATUSES),
                    "failed": sum(1 for status in run_statuses if status in FAILED_RUN_STATUSES),
                },
                "improvement_counts": {
                    "total": len(req_improvements),
                    "open": unresolved_improvements,
                    "resolved": len(req_improvements) - unresolved_improvements,
                },
                "last_activity_at": last_activity_at,
                "health_score": health_score,
                "risk_level": risk_level,
                "stability_score": intelligence["stability_score"],
                "retry_count": intelligence["retry_count"],
                "unresolved_count": intelligence["unresolved_count"],
                "recurring_failure_patterns": intelligence["recurring_failure_patterns"],
                "most_impacted_modules": intelligence["most_impacted_modules"],
                "ai_spend_cents": round(sum(ai_cost_by_run.get(run.id, 0.0) for run in req_runs), 4),
                "ai_total_tokens": int(sum(ai_tokens_by_run.get(run.id, 0) for run in req_runs)),
            }
        )

    cards.sort(
        key=lambda row: (
            row.get("last_activity_at") is None,
            row.get("last_activity_at"),
            row.get("requirement_id"),
        ),
        reverse=True,
    )
    total = len(cards)
    sliced = cards[offset : offset + limit]
    next_offset = offset + limit if (offset + limit) < total else None
    return {"items": sliced, "total": total, "limit": limit, "offset": offset, "next_offset": next_offset}


async def build_requirement_timeline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    requirement_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    summary = await build_requirement_summary(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=10_000,
        offset=0,
    )
    cards = summary["items"]
    if requirement_id not in {card["requirement_id"] for card in cards}:
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "next_offset": None}

    tasks = (
        await session.execute(
            select(Task).where(Task.tenant_id == tenant_id, Task.project_id == project_id, Task.deleted_at.is_(None))
        )
    ).scalars().all()
    linked_tasks = [task for task in tasks if requirement_id in _task_requirement_ids(task)]
    task_ids = {task.id for task in linked_tasks}

    runs = (
        await session.execute(select(Run).where(Run.tenant_id == tenant_id, Run.project_id == project_id))
    ).scalars().all()
    tasks_by_id = {task.id: task for task in tasks}
    tasks_by_run: dict[uuid.UUID, list[Task]] = {}
    for task in tasks:
        if task.run_id:
            tasks_by_run.setdefault(task.run_id, []).append(task)
    linked_runs = [
        run for run in runs if requirement_id in _run_requirement_ids(run, tasks_by_id=tasks_by_id, tasks_by_run=tasks_by_run)
    ]
    run_ids = {run.id for run in linked_runs}

    improvements = (
        await session.execute(
            select(ImprovementRequest).where(ImprovementRequest.tenant_id == tenant_id, ImprovementRequest.project_id == project_id)
        )
    ).scalars().all()
    linked_improvements = [item for item in improvements if item.source_run_id in run_ids]

    events: list[dict[str, Any]] = []
    try:
        graph = requirements_service.get_graph(str(project_id))
        req_node = next((node for node in getattr(graph, "nodes", []) if getattr(node, "id", None) == requirement_id), None)
        if req_node is not None:
            text = str(getattr(req_node, "text", "") or "").strip()
            events.append(
                {
                    "type": "requirement.created",
                    "title": f"Requirement {requirement_id} created",
                    "description": text[:240] if text else requirement_id,
                    "source_type": "requirement_graph",
                    "source_id": requirement_id,
                    "status": str(getattr(graph, "status", "DRAFT")),
                    "created_at": getattr(graph, "created_at", None),
                }
            )
            events.append(
                {
                    "type": "requirement.updated",
                    "title": f"Requirement {requirement_id} updated",
                    "description": text[:240] if text else requirement_id,
                    "source_type": "requirement_graph",
                    "source_id": requirement_id,
                    "status": str(getattr(graph, "status", "DRAFT")),
                    "created_at": getattr(graph, "updated_at", None),
                }
            )
    except RequirementGraphNotFoundError:
        pass

    for task in linked_tasks:
        events.append(
            {
                "type": "task.updated",
                "title": task.title,
                "description": task.description,
                "source_type": "task",
                "source_id": str(task.id),
                "status": task.status,
                "created_at": task.updated_at or task.created_at,
            }
        )
        if task.status in {"DONE", "COMPLETED", "CLOSED"}:
            events.append(
                {
                    "type": "task.completed",
                    "title": task.title,
                    "description": "Task completed",
                    "source_type": "task",
                    "source_id": str(task.id),
                    "status": task.status,
                    "created_at": task.finished_at or task.updated_at or task.created_at,
                }
            )
        if task.status in {"FAILED", "CANCELED", "BLOCKED"}:
            events.append(
                {
                    "type": "task.failed",
                    "title": task.title,
                    "description": task.last_error,
                    "source_type": "task",
                    "source_id": str(task.id),
                    "status": task.status,
                    "created_at": task.finished_at or task.updated_at or task.created_at,
                }
            )

    for run in linked_runs:
        summary_data = run.summary if isinstance(run.summary, dict) else {}
        events.append(
            {
                "type": "run.started",
                "title": f"Run {run.id}",
                "description": summary_data.get("goal") or summary_data.get("strategy_goal"),
                "source_type": "run",
                "source_id": str(run.id),
                "status": run.status,
                "created_at": run.started_at or run.created_at,
            }
        )
        if run.status in {"COMPLETED"}:
            events.append(
                {
                    "type": "run.completed",
                    "title": f"Run {run.id} completed",
                    "description": summary_data.get("goal") or summary_data.get("strategy_goal"),
                    "source_type": "run",
                    "source_id": str(run.id),
                    "status": run.status,
                    "created_at": run.finished_at or run.updated_at or run.created_at,
                }
            )
        if run.status in {"FAILED", "CANCELED"}:
            events.append(
                {
                    "type": "run.failed",
                    "title": f"Run {run.id} failed",
                    "description": summary_data.get("primary_error") or run.workspace_error,
                    "source_type": "run",
                    "source_id": str(run.id),
                    "status": run.status,
                    "created_at": run.finished_at or run.updated_at or run.created_at,
                }
            )
        pr_url = summary_data.get("pull_request_url")
        if isinstance(pr_url, str) and pr_url.strip():
            events.append(
                {
                    "type": "pr.created",
                    "title": "Pull request created",
                    "description": pr_url,
                    "source_type": "run",
                    "source_id": str(run.id),
                    "status": run.status,
                    "created_at": run.updated_at or run.finished_at or run.created_at,
                }
            )

    for item in linked_improvements:
        item_status = str(item.status or "").upper()
        events.append(
            {
                "type": "improvement.requested",
                "title": item.goal_text or "Improvement requested",
                "description": item.issue_text,
                "source_type": "improvement_request",
                "source_id": str(item.id),
                "status": item.status,
                "created_at": item.created_at,
            }
        )
        if item_status in {"COMPLETED", "DONE", "RESOLVED"}:
            events.append(
                {
                    "type": "improvement.resolved",
                    "title": item.goal_text or "Improvement resolved",
                    "description": item.issue_text,
                    "source_type": "improvement_request",
                    "source_id": str(item.id),
                    "status": item.status,
                    "created_at": item.updated_at or item.created_at,
                }
            )

    events = [event for event in events if event.get("created_at") is not None]
    events.sort(key=lambda event: event["created_at"], reverse=True)
    total = len(events)
    sliced = events[offset : offset + limit]
    next_offset = offset + limit if (offset + limit) < total else None
    return {"items": sliced, "total": total, "limit": limit, "offset": offset, "next_offset": next_offset}
