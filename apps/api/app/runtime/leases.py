from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, WorkItem
from app.services.event_log import record_event
from app.services.state_guard import update_work_item_status


log = logging.getLogger("app.runtime.leases")

DEFAULT_CLAIM_LEASE_SECONDS = 300
MIN_LEASE_SECONDS = 60
LEASE_BUFFER_SECONDS = 60


@dataclass(frozen=True)
class ReclaimedLease:
    work_item_id: uuid.UUID
    run_id: uuid.UUID
    project_id: uuid.UUID
    previous_status: str
    lease_expires_at: datetime | None


def lease_seconds_for_executor(settings, executor_name: str) -> int:
    executor = (executor_name or "").lower()
    if executor == "codex":
        timeout = int(getattr(settings, "codex_timeout_seconds", 0) or 0)
    elif executor == "test":
        timeout = int(getattr(settings, "test_timeout_seconds", 0) or 0)
    else:
        timeout = 0
    return max(MIN_LEASE_SECONDS, timeout + LEASE_BUFFER_SECONDS)


def lease_refresh_interval_seconds(lease_seconds: int) -> float:
    lease = max(1, lease_seconds)
    return max(5.0, min(15.0, lease / 3))


async def reclaim_expired_work_items(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[ReclaimedLease]:
    current_time = now or datetime.now(timezone.utc)
    stmt = select(WorkItem).where(
        WorkItem.status.in_(["CLAIMED", "RUNNING"]),
        WorkItem.lease_expires_at.isnot(None),
        WorkItem.lease_expires_at < current_time,
    )
    if run_id is not None:
        stmt = stmt.where(WorkItem.run_id == run_id)

    expired_items = (await session.execute(stmt.order_by(WorkItem.created_at, WorkItem.id))).scalars().all()
    recovered: list[ReclaimedLease] = []
    for item in expired_items:
        previous_status = item.status
        previous_lease = item.lease_expires_at
        ok = await update_work_item_status(
            session,
            item.id,
            ["CLAIMED", "RUNNING"],
            "QUEUED",
            assigned_agent_id=None,
            lease_expires_at=None,
            started_at=None,
        )
        if not ok:
            continue
        await record_event(
            session,
            project_id=item.project_id,
            run_id=item.run_id,
            work_item_id=item.id,
            event_type="WORK_ITEM_LEASE_EXPIRED",
            actor_type="SYSTEM",
            payload={
                "work_item_id": str(item.id),
                "previous_status": previous_status,
                "lease_expires_at": previous_lease.isoformat() if previous_lease else None,
            },
            tenant_id=item.tenant_id,
        )
        recovered.append(
            ReclaimedLease(
                work_item_id=item.id,
                run_id=item.run_id,
                project_id=item.project_id,
                previous_status=previous_status,
                lease_expires_at=previous_lease,
            )
        )
    return recovered


async def keep_work_item_lease_alive(
    session_factory: Callable[[], AsyncSession],
    *,
    agent_id: uuid.UUID,
    work_item_id: uuid.UUID,
    lease_seconds: int,
    interval_seconds: float | None = None,
) -> None:
    refresh_interval = interval_seconds or lease_refresh_interval_seconds(lease_seconds)
    try:
        while True:
            await asyncio.sleep(refresh_interval)
            async with session_factory() as session:
                item = await session.get(WorkItem, work_item_id)
                agent = await session.get(Agent, agent_id)
                if item is None or agent is None:
                    await session.commit()
                    return
                if item.assigned_agent_id != agent_id or item.status not in {"CLAIMED", "RUNNING"}:
                    await session.commit()
                    return
                now = datetime.now(timezone.utc)
                agent.last_heartbeat_at = now
                item.lease_expires_at = now + timedelta(seconds=lease_seconds)
                session.add(agent)
                session.add(item)
                await session.commit()
    except asyncio.CancelledError:
        return
    except Exception:
        log.exception("Failed to refresh active work item lease work_item_id=%s agent_id=%s", work_item_id, agent_id)


async def reclaim_orphaned_work_items(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
) -> list[ReclaimedLease]:
    """Requeue claimed/running work items whose assigned worker is missing or inactive."""
    stmt = (
        select(WorkItem)
        .outerjoin(Agent, Agent.id == WorkItem.assigned_agent_id)
        .where(
            WorkItem.status.in_(["CLAIMED", "RUNNING"]),
            or_(WorkItem.assigned_agent_id.is_(None), Agent.id.is_(None), Agent.status != "ACTIVE"),
        )
    )
    if run_id is not None:
        stmt = stmt.where(WorkItem.run_id == run_id)

    orphaned_items = (await session.execute(stmt.order_by(WorkItem.created_at, WorkItem.id))).scalars().all()
    recovered: list[ReclaimedLease] = []
    for item in orphaned_items:
        previous_status = item.status
        previous_lease = item.lease_expires_at
        ok = await update_work_item_status(
            session,
            item.id,
            ["CLAIMED", "RUNNING"],
            "QUEUED",
            assigned_agent_id=None,
            lease_expires_at=None,
            started_at=None,
        )
        if not ok:
            continue
        await record_event(
            session,
            project_id=item.project_id,
            run_id=item.run_id,
            work_item_id=item.id,
            event_type="WORK_ITEM_REQUEUED",
            actor_type="SYSTEM",
            payload={
                "work_item_id": str(item.id),
                "reason": "orphaned_worker_assignment",
                "previous_status": previous_status,
            },
            tenant_id=item.tenant_id,
        )
        recovered.append(
            ReclaimedLease(
                work_item_id=item.id,
                run_id=item.run_id,
                project_id=item.project_id,
                previous_status=previous_status,
                lease_expires_at=previous_lease,
            )
        )
    return recovered
