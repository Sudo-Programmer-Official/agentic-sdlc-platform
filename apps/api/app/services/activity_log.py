from __future__ import annotations

import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog

_ENTITY_TYPE_MAX_LEN = 32
_ACTION_TYPE_MAX_LEN = 32
_EVENT_TYPE_MAX_LEN = 32
_ACTOR_MAX_LEN = 100


def _trim(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


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
        entity_type=_trim(entity_type, _ENTITY_TYPE_MAX_LEN) or "project",
        entity_id=entity_id,
        action_type=_trim(action_type, _ACTION_TYPE_MAX_LEN) or "unknown",
        event_type=_trim(event_type, _EVENT_TYPE_MAX_LEN),
        previous_state=jsonable_encoder(previous_state) if previous_state is not None else None,
        new_state=jsonable_encoder(new_state) if new_state is not None else None,
        extra_metadata=jsonable_encoder(metadata) if metadata is not None else None,
        actor=_trim(actor, _ACTOR_MAX_LEN),
    )
    session.add(entry)
