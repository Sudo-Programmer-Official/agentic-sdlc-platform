from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, RunEvent


async def record_event(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    event_type: str,
    task_id: uuid.UUID | None = None,
    work_item_id: uuid.UUID | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    tenant_id: uuid.UUID | None = None,
) -> RunEvent:
    if tenant_id is None:
        tenant_id = await session.scalar(select(Run.tenant_id).where(Run.id == run_id))
    if tenant_id is None:
        tenant_id = uuid.UUID(int=0)
    event = RunEvent(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        task_id=task_id,
        work_item_id=work_item_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        message=message,
        payload=payload,
        correlation_id=correlation_id,
    )
    session.add(event)
    return event
