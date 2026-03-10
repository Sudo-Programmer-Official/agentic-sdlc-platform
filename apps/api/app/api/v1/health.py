from __future__ import annotations

import uuid
from typing import Any

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, exists, func, text, desc
from sqlalchemy.ext.asyncio import AsyncSession
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.models import Project, Document, Task, Trace
from app.db.models import Run, WorkItem
from app.db.session import get_session
from app.core.config import get_settings
from app.startup import resolve_alembic_config_path

# Keep legacy /store/... routes and add public /projects/... routes to match frontend calls.
router = APIRouter(prefix="/store", tags=["health"])
public_router = APIRouter(tags=["health"])


@router.get("/projects/{project_id}/health")
@public_router.get("/projects/{project_id}/health")
async def project_health(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    orphan_tasks_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(Task.project_id == project_id, Task.document_id.is_(None), Task.deleted_at.is_(None))
            .subquery()
        )
    )

    docs_without_tasks_count = await session.scalar(
        select(func.count()).select_from(
            select(Document.id)
            .where(
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
                ~exists().where(Task.document_id == Document.id, Task.deleted_at.is_(None)),
            )
            .subquery()
        )
    )

    tasks_without_trace_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.deleted_at.is_(None),
                ~exists().where(
                    Trace.project_id == project_id,
                    Trace.to_id == Task.id,
                    Trace.to_type == "task",
                    Trace.from_type == "document",
                    Trace.deleted_at.is_(None),
                ),
            )
            .subquery()
        )
    )

    deprecated_without_supersede_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.status == "DEPRECATED",
                Task.deleted_at.is_(None),
                ~exists().where(
                    Trace.project_id == project_id,
                    Trace.from_id == Task.id,
                    Trace.relation_type == "supersedes",
                    Trace.deleted_at.is_(None),
                ),
            )
            .subquery()
        )
    )

    # Cycle detection
    traces = (
        await session.execute(
            select(Trace.from_id, Trace.to_id).where(
                Trace.project_id == project_id,
                Trace.deleted_at.is_(None),
            )
        )
    ).all()
    adj: dict[uuid.UUID, list[uuid.UUID]] = {}
    for f, t in traces:
        adj.setdefault(f, []).append(t)

    cycles = []
    visited: set[uuid.UUID] = set()
    stack: set[uuid.UUID] = set()

    def dfs(node: uuid.UUID, path: list[uuid.UUID]):
        if node in stack:
            try:
                idx = path.index(node)
                cycles.append(path[idx:])
            except ValueError:
                cycles.append(path + [node])
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        for nei in adj.get(node, []):
            if len(cycles) >= 3:
                break
            dfs(nei, path + [nei])
        stack.remove(node)

    for node in adj.keys():
        if len(cycles) >= 3:
            break
        dfs(node, [node])

    # longest chain length (approx via DFS depth)
    longest_chain = 0
    for node in adj.keys():
        seen = set()
        def depth(n):
            if n in seen:
                return 0
            seen.add(n)
            if not adj.get(n):
                return 1
            return 1 + max(depth(child) for child in adj.get(n, []))
        longest_chain = max(longest_chain, depth(node))

    return {
        "orphan_tasks": orphan_tasks_count > 0,
        "docs_without_tasks": docs_without_tasks_count > 0,
        "tasks_without_trace": tasks_without_trace_count > 0,
        "deprecated_without_supersede": deprecated_without_supersede_count > 0,
        "graph_cycles_detected": len(cycles) > 0,
        "counts": {
            "orphan_tasks": orphan_tasks_count,
            "docs_without_tasks": docs_without_tasks_count,
            "tasks_without_trace": tasks_without_trace_count,
            "deprecated_without_supersede": deprecated_without_supersede_count,
            "cycles": len(cycles),
            "longest_chain": longest_chain,
        },
        "sample_cycles": cycles,
    }


def _alembic_head() -> str | None:
    try:
        config_path = resolve_alembic_config_path()
        if config_path is None:
            return None
        cfg = Config(str(config_path))
        cfg.set_main_option("script_location", str(config_path.parent / "alembic"))
        script = ScriptDirectory.from_config(cfg)
        return script.get_current_head()
    except Exception:
        return None


@public_router.get("/health/detail")
async def health_detail(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    # DB connectivity
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": os.getenv("BUILD_VERSION", "build-2026-02-26-1"),
        "environment": settings.env,
        "database_connected": db_ok,
        "alembic_head": _alembic_head(),
    }


@public_router.get("/health/metrics")
async def health_metrics(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    # Lightweight aggregate metrics (DB-based)
    runs_row = (
        await session.execute(
            select(
                func.count().filter(Run.status == "RUNNING"),
                func.count().filter(Run.status == "COMPLETED"),
                func.count().filter(Run.status == "FAILED"),
            )
        )
    ).first()
    work_items_row = (
        await session.execute(
            select(
                func.count().filter(WorkItem.status == "RUNNING"),
                func.count().filter(WorkItem.status == "DONE"),
                func.count().filter(WorkItem.status == "FAILED"),
                func.count().filter(WorkItem.status == "CLAIMED"),
                func.count().filter(WorkItem.status == "QUEUED"),
            )
        )
    ).first()

    # Load recent runs for telemetry (limit to keep light)
    recent_runs = (
        await session.execute(select(Run).order_by(desc(Run.created_at)).limit(200))
    ).scalars().all()
    recent_run_ids = [r.id for r in recent_runs]
    if recent_run_ids:
        wi_rows = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id.in_(recent_run_ids))
            )
        ).scalars().all()
    else:
        wi_rows = []

    # Aggregate usage and metrics in Python to avoid heavy SQL JSON manipulation
    total_input = total_output = 0
    tokens_per_run: dict[uuid.UUID, int] = {}
    fix_attempts_per_run: dict[uuid.UUID, int] = {}
    review_fail_runs: set[uuid.UUID] = set()
    patch_guard_failures = 0
    durations: list[float] = []
    risk_scores: list[float] = []
    confidences: list[float] = []
    patch_lines: list[int] = []

    for wi in wi_rows:
        usage = (wi.result or {}).get("usage") or {}
        it = usage.get("input_tokens") or 0
        ot = usage.get("output_tokens") or 0
        total_input += it
        total_output += ot
        tokens_per_run[wi.run_id] = tokens_per_run.get(wi.run_id, 0) + it + ot

        if wi.type == "FIX_TEST_FAILURE":
            fix_attempts_per_run[wi.run_id] = fix_attempts_per_run.get(wi.run_id, 0) + 1
        if wi.type == "REVIEW_DIFF" and wi.status == "FAILED":
            review_fail_runs.add(wi.run_id)
        if wi.status == "FAILED":
            msg = (wi.result or {}).get("message") or ""
            if isinstance(msg, str) and (
                "Patch too" in msg or "Patch apply" in msg or "secret_pattern_detected" in msg
            ):
                patch_guard_failures += 1
        # Review metrics
        review = (wi.result or {}).get("review") or {}
        if isinstance(review, dict):
            rs = review.get("risk_score")
            cf = review.get("confidence")
            pl = review.get("patch_lines")
            if isinstance(rs, (int, float)):
                risk_scores.append(float(rs))
            if isinstance(cf, (int, float)):
                confidences.append(float(cf))
            if isinstance(pl, (int, float)):
                patch_lines.append(int(pl))

    for run in recent_runs:
        if run.status == "COMPLETED" and run.finished_at and run.created_at:
            durations.append((run.finished_at - run.created_at).total_seconds())

    completed_token_totals = [tokens_per_run[r.id] for r in recent_runs if r.status == "COMPLETED" and r.id in tokens_per_run]

    return {
        "runs": {
            "running": runs_row[0],
            "completed": runs_row[1],
            "failed": runs_row[2],
        },
        "work_items": {
            "running": work_items_row[0],
            "done": work_items_row[1],
            "failed": work_items_row[2],
            "claimed": work_items_row[3],
            "queued": work_items_row[4],
        },
        "usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "avg_tokens_per_successful_run": (sum(completed_token_totals) / len(completed_token_totals))
            if completed_token_totals
            else 0,
        },
        "telemetry": {
            "avg_fix_attempts_per_run": (sum(fix_attempts_per_run.values()) / len(recent_run_ids)) if recent_run_ids else 0,
            "runs_failed_due_to_review": len(review_fail_runs),
            "runs_failed_due_to_patch_guard": patch_guard_failures,
            "time_to_green_avg_seconds": (sum(durations) / len(durations)) if durations else 0,
            "avg_risk_score": (sum(risk_scores) / len(risk_scores)) if risk_scores else 0,
            "avg_confidence": (sum(confidences) / len(confidences)) if confidences else 0,
            "avg_patch_lines": (sum(patch_lines) / len(patch_lines)) if patch_lines else 0,
        },
    }
