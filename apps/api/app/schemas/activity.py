from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ActivityOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    entity_type: str
    entity_id: Optional[uuid.UUID] = None
    action_type: str
    metadata: Optional[dict] = Field(default=None, validation_alias=AliasChoices("extra_metadata", "metadata"))
    actor: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
