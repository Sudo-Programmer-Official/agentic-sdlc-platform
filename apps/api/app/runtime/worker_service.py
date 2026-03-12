from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, and_, exists

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Agent, WorkItem
from app.runtime.context import RunContext
from app.runtime.registry import get_executor
from app.services.event_log import record_event
from app.services.runtime_lineage import link_run_to_work_item, persist_work_item_artifacts
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()


async def enqueue_fix_item(session, failed_wi: WorkItem) -> None:
    # cap attempts
    count = (
        await session.execute(
            select(func.count()).where(
                WorkItem.run_id == failed_wi.run_id,
                WorkItem.type == "FIX_TEST_FAILURE",
            )
        )
    ).scalar() or 0
    if count >= settings.max_fix_attempts_per_run:
        return
    fix = WorkItem(
        project_id=failed_wi.project_id,
        tenant_id=failed_wi.tenant_id,
        run_id=failed_wi.run_id,
        type="FIX_TEST_FAILURE",
        key=f"FIX_TEST_FAILURE_{count + 1}",
        status="QUEUED",
        executor="codex",
        priority=9,
        required_capabilities=["code"],
        payload={
            "test_exit_code": (failed_wi.result or {}).get("exit_code"),
            "stdout": (failed_wi.result or {}).get("stdout"),
            "stderr": (failed_wi.result or {}).get("stderr"),
        },
    )
    session.add(fix)
    await session.flush()
    await link_run_to_work_item(session, fix)
    await record_event(
        session,
        project_id=fix.project_id,
        run_id=fix.run_id,
        work_item_id=fix.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(fix.id), "type": fix.type},
    )


async def enqueue_test_run(session, source_wi: WorkItem) -> None:
    # mark previous failed RUN_TESTS as superseded (keep status FAILED for audit)
    prev_failed = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == source_wi.run_id,
                WorkItem.type == "RUN_TESTS",
                WorkItem.status == "FAILED",
            )
        )
    ).scalars().all()
    for pf in prev_failed:
        payload = pf.result or {}
        payload["superseded"] = True
        payload["superseded_by"] = str(source_wi.id)
        pf.result = payload
        session.add(pf)
    test = WorkItem(
        project_id=source_wi.project_id,
        tenant_id=source_wi.tenant_id,
        run_id=source_wi.run_id,
        type="RUN_TESTS",
        key=f"RUN_TESTS_{uuid.uuid4().hex[:4]}",
        status="QUEUED",
        executor="test",
        priority=8,
        required_capabilities=["test"],
        payload={},
    )
    session.add(test)
    await session.flush()
    await link_run_to_work_item(session, test)
    await record_event(
        session,
        project_id=test.project_id,
        run_id=test.run_id,
        work_item_id=test.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(test.id), "type": test.type},
    )


async def execute_item(session, wi: WorkItem, agent: Agent):
    executor = get_executor(wi.executor)
    context = RunContext(project_id=wi.project_id, run_id=wi.run_id)
    try:
        result = await executor.execute(wi, context)
        wi.status = result.get("status", "DONE")
        wi.result = result.get("payload", {})
        wi.finished_at = datetime.now(timezone.utc)
        wi.last_error = None
        session.add(wi)
        await persist_work_item_artifacts(session, wi, (wi.result or {}).get("artifacts"))
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
    except Exception as exc:
        wi.status = "FAILED"
        wi.finished_at = datetime.now(timezone.utc)
        wi.last_error = str(exc)
        session.add(wi)
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_FAILED",
            actor_type="AGENT",
            actor_id=str(agent.id),
            payload={"work_item_id": str(wi.id), "error": str(exc)},
        )


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
