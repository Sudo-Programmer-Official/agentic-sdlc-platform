from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog


async def log_activity(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action_type: str,
    event_type: str | None = None,
    metadata: dict | None = None,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    actor: str | None = None,
) -> None:
    entry = ActivityLog(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action_type=action_type,
        event_type=event_type,
        previous_state=previous_state,
        new_state=new_state,
        extra_metadata=metadata,
        actor=actor,
    )
    session.add(entry)
