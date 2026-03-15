from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import select, and_, exists

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Agent, Run, WorkItem
from app.runtime.registry import build_executor
from app.runtime.recovery_policy import maybe_apply_recovery
from app.services.event_log import record_event
from app.services.runtime_lineage import persist_work_item_artifacts
from app.services.workspace_supervisor import build_run_context
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()


async def execute_item(session, wi: WorkItem, agent: Agent):
    run = await session.get(Run, wi.run_id)
    if run is None:
        return
    failure_stage = "workspace_context"
    try:
        context = await build_run_context(session, run, require_repo=wi.executor in {"codex", "test"})
        executor = build_executor(wi.executor, repo_root=None if not context.repo_path else Path(context.repo_path))
        failure_stage = "executor_execute"
        result = await executor.execute(wi, context)
        wi.status = result.get("status", "DONE")
        wi.result = result.get("payload", {})
        wi.finished_at = datetime.now(timezone.utc)
        wi.last_error = None
        session.add(wi)
        failure_stage = "artifact_persistence"
        await persist_work_item_artifacts(session, wi, (wi.result or {}).get("artifacts"))
        failure_stage = "event_recording"
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_DONE" if wi.status == "DONE" else "WORK_ITEM_FAILED",
            actor_type="AGENT",
            actor_id=str(agent.id),
            payload={"work_item_id": str(wi.id), "status": wi.status},
        )
        await session.flush()
        failure_stage = "recovery_policy"
        await maybe_apply_recovery(session, wi)
    except Exception as exc:
        await session.rollback()
        failed_item = await session.get(WorkItem, wi.id)
        if failed_item is None:
            return
        failed_item.status = "FAILED"
        failed_item.finished_at = datetime.now(timezone.utc)
        failed_item.last_error = str(exc)
        session.add(failed_item)
        await record_event(
            session,
            project_id=failed_item.project_id,
            run_id=failed_item.run_id,
            work_item_id=failed_item.id,
            event_type="WORK_ITEM_FAILED",
            actor_type="AGENT",
            actor_id=str(agent.id),
            tenant_id=failed_item.tenant_id,
            payload={
                "work_item_id": str(failed_item.id),
                "error": str(exc),
                "exception_class": exc.__class__.__name__,
                "failure_stage": failure_stage,
            },
        )
        await session.flush()
        await maybe_apply_recovery(session, failed_item)


async def tick_worker(agent_id: uuid.UUID):
    settings = get_settings()
    if settings.runtime_mode != "external":
        return
    async with SessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        if not agent or agent.status != "ACTIVE":
            return
        # claim one item
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=60)
        agent.last_heartbeat_at = now
        session.add(agent)
        agent_caps = set(agent.capabilities or [])
        agent_executors = set(agent.executors or [])
        # Prevent multiple RUN_TESTS per run at once
        from sqlalchemy.orm import aliased
        other = aliased(WorkItem)
        result = await session.execute(
            select(WorkItem)
            .where(
                WorkItem.status == "QUEUED",
                ~exists().where(
                    and_(
                        other.run_id == WorkItem.run_id,
                        other.type == "RUN_TESTS",
                        other.status == "RUNNING",
                    )
                ),
            )
            .order_by(WorkItem.priority.desc(), WorkItem.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        wi = None
        for candidate in result.scalars().all():
            req_caps = set(candidate.required_capabilities or [])
            if req_caps and not req_caps.issubset(agent_caps):
                continue
            if agent_executors and candidate.executor not in agent_executors:
                continue
            wi = candidate
            break
        if not wi:
            await session.commit()
            return
        wi.status = "RUNNING"
        wi.assigned_agent_id = agent_id
        wi.lease_expires_at = lease_expires
        session.add(wi)
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_CLAIMED",
            actor_type="AGENT",
            actor_id=str(agent_id),
            payload={"work_item_id": str(wi.id), "agent_id": str(agent_id)},
        )
        await session.commit()

    # execute outside the claim transaction
    async with SessionLocal() as session:
        wi = await session.get(WorkItem, wi.id)
        agent = await session.get(Agent, agent_id)
        if not wi or not agent:
            return
        await execute_item(session, wi, agent)
        await session.commit()


async def main():
    settings = get_settings()
    agent_id = uuid.uuid4()
    # Register ephemeral worker agent record
    async with SessionLocal() as session:
        agent = Agent(
            id=agent_id,
            name=f"worker-{agent_id.hex[:8]}",
            kind="worker",
            executors=["dummy", "codex", "test"],
            capabilities=["code", "test", "review", "plan"],
            max_concurrency=1,
            status="ACTIVE",
            last_heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(agent)
        await session.commit()

    while True:
        try:
            await tick_worker(agent_id)
        except Exception:
            pass
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
