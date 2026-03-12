from __future__ import annotations

import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
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
        previous_state=jsonable_encoder(previous_state) if previous_state is not None else None,
        new_state=jsonable_encoder(new_state) if new_state is not None else None,
        extra_metadata=jsonable_encoder(metadata) if metadata is not None else None,
        actor=actor,
    )
    session.add(entry)
