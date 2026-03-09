from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, WorkItem


async def update_run_status(
    session: AsyncSession,
    run_id: uuid.UUID,
    from_statuses: Iterable[str],
    to_status: str,
    set_finished: bool = False,
) -> bool:
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.status.in_(list(from_statuses)))
        .values(status=to_status)
    )
    if set_finished:
        from datetime import datetime, timezone

        stmt = stmt.values(finished_at=datetime.now(timezone.utc))
    result = await session.execute(stmt)
    return result.rowcount == 1


async def update_work_item_status(
    session: AsyncSession,
    work_item_id: uuid.UUID,
    from_statuses: Iterable[str],
    to_status: str,
    **kwargs,
) -> bool:
    stmt = (
        update(WorkItem)
        .where(WorkItem.id == work_item_id, WorkItem.status.in_(list(from_statuses)))
        .values(status=to_status, **kwargs)
    )
    result = await session.execute(stmt)
    return result.rowcount == 1
