from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactCreate(BaseModel):
    task_id: Optional[uuid.UUID] = None
    run_id: Optional[uuid.UUID] = None
    work_item_id: Optional[uuid.UUID] = None
    type: str
    uri: str
    version: int = 1
    metadata: Optional[Any] = None


class ArtifactOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_id: Optional[uuid.UUID]
    run_id: Optional[uuid.UUID]
    work_item_id: Optional[uuid.UUID]
    type: str
    uri: str
    version: int
    metadata: Optional[Any] = Field(default=None, validation_alias="extra_metadata")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
