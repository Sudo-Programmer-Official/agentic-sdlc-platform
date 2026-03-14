from __future__ import annotations

import copy
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace, WorkItem, WorkItemEdge
from app.runtime.orchestrator import RunOrchestrator
from app.db.session import SessionLocal
from app.services.activity_log import log_activity
from app.services.event_log import record_event
from app.services.run_launch import _schedule_orchestrator_start
from app.services.workspace_supervisor import ensure_run_workspace

log = logging.getLogger("app.run_replay")


def _fork_branch_name(source_run: Run, override: str | None) -> str:
    if override:
        return override.strip()
    base = source_run.branch_name or f"run/{str(source_run.id)[:8]}"
    return f"{base}-fork"


def _fork_summary(source_run: Run, overrides: dict[str, Any] | None) -> dict[str, Any]:
    summary = copy.deepcopy(source_run.summary or {})
    summary["forked_from_run_id"] = str(source_run.id)
    summary["forked_from_status"] = source_run.status
    if overrides:
        summary.update(overrides)
    return summary


def _fork_work_item_executor(source_run: Run, target_executor: str, source_item: WorkItem) -> str:
    if source_item.type == "RUN_TESTS" and target_executor not in {"dummy", "test"}:
        return "test"
    if source_item.executor == source_run.executor:
        return target_executor
    if source_item.executor == "dummy" and target_executor != "dummy" and source_item.type != "RUN_TESTS":
        return target_executor
    return source_item.executor


async def fork_run(
    session: AsyncSession,
    *,
    source_run: Run,
    executor: str | None = None,
    branch_name: str | None = None,
    summary_overrides: dict[str, Any] | None = None,
    start_now: bool = True,
) -> Run:
    target_executor = (executor or source_run.executor or "dummy").lower()
    forked_run = Run(
        project_id=source_run.project_id,
        tenant_id=source_run.tenant_id,
        status="QUEUED",
        executor=target_executor,
        summary=_fork_summary(source_run, summary_overrides),
        branch_name=_fork_branch_name(source_run, branch_name),
    )
    session.add(forked_run)
    await session.flush()

    repo_source = None
    if source_run.repo_path:
        candidate = Path(source_run.repo_path)
        if candidate.exists():
            repo_source = candidate
    await ensure_run_workspace(
        session,
        forked_run,
        require_repo=target_executor in {"codex", "test"},
        repo_source_path=repo_source,
    )

    source_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == source_run.id)
            .order_by(WorkItem.created_at.asc(), WorkItem.id.asc())
        )
    ).scalars().all()
    item_id_map: dict[uuid.UUID, uuid.UUID] = {}
    forked_items: list[WorkItem] = []
    for source_item in source_items:
        cloned = WorkItem(
            project_id=source_item.project_id,
            tenant_id=source_item.tenant_id,
            run_id=forked_run.id,
            type=source_item.type,
            key=source_item.key,
            status="QUEUED",
            priority=source_item.priority,
            executor=_fork_work_item_executor(source_run, target_executor, source_item),
            assigned_agent_id=None,
            attempt=0,
            max_attempts=source_item.max_attempts,
            lease_expires_at=None,
            depends_on_count=source_item.depends_on_count,
            required_capabilities=copy.deepcopy(source_item.required_capabilities or []),
            payload=copy.deepcopy(source_item.payload or {}),
            result={},
            started_at=None,
            finished_at=None,
            last_error=None,
        )
        session.add(cloned)
        await session.flush()
        item_id_map[source_item.id] = cloned.id
        forked_items.append(cloned)
        session.add(
            Trace(
                tenant_id=source_item.tenant_id,
                project_id=source_item.project_id,
                from_type="work_item",
                from_id=source_item.id,
                to_type="work_item",
                to_id=cloned.id,
                relation_type="forks",
                relation_strength=1.0,
            )
        )

    source_edges = (
        await session.execute(
            select(WorkItemEdge).where(WorkItemEdge.run_id == source_run.id)
        )
    ).scalars().all()
    for source_edge in source_edges:
        session.add(
            WorkItemEdge(
                tenant_id=source_edge.tenant_id,
                run_id=forked_run.id,
                from_work_item_id=item_id_map[source_edge.from_work_item_id],
                to_work_item_id=item_id_map[source_edge.to_work_item_id],
            )
        )

    session.add(
        Trace(
            tenant_id=source_run.tenant_id,
            project_id=source_run.project_id,
            from_type="run",
            from_id=source_run.id,
            to_type="run",
            to_id=forked_run.id,
            relation_type="forks",
            relation_strength=1.0,
        )
    )
    await log_activity(
        session,
        project_id=forked_run.project_id,
        entity_type="run",
        entity_id=forked_run.id,
        action_type="run.forked",
        metadata={
            "forked_from_run_id": str(source_run.id),
            "executor": forked_run.executor,
            "start_now": start_now,
        },
    )
    await record_event(
        session,
        project_id=forked_run.project_id,
        run_id=forked_run.id,
        event_type="RUN_FORKED",
        actor_type="USER",
        payload={
            "forked_from_run_id": str(source_run.id),
            "forked_from_status": source_run.status,
            "executor": forked_run.executor,
            "work_item_count": len(forked_items),
            "start_now": start_now,
        },
        tenant_id=forked_run.tenant_id,
    )
    await session.commit()
    await session.refresh(forked_run)

    if start_now:
        orchestrator = RunOrchestrator(SessionLocal, executor_name=forked_run.executor)
        try:
            await orchestrator.bootstrap_in_session(
                session,
                forked_run.id,
                actor_type="USER",
                executor_name=forked_run.executor,
            )
        except Exception:
            log.exception("Run bootstrap failed for replay run_id=%s project_id=%s", forked_run.id, forked_run.project_id)
            raise
        await session.refresh(forked_run)
        bind = session.get_bind()
        is_sqlite = bind is not None and bind.dialect.name == "sqlite"
        if not is_sqlite:
            _schedule_orchestrator_start(
                orchestrator,
                run_id=forked_run.id,
                actor_type="USER",
                actor_id=None,
                executor_name=forked_run.executor,
            )
        else:
            log.info(
                "Run execution handoff deferred run_id=%s project_id=%s reason=sqlite_test_session",
                forked_run.id,
                forked_run.project_id,
            )

    return forked_run
