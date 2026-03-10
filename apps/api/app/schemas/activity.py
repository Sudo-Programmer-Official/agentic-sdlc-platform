from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ActivityOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    entity_type: str
    entity_id: Optional[uuid.UUID] = None
    action_type: str
    metadata: Optional[dict] = None
    actor: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
