from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class ArtifactCreate(BaseModel):
    task_id: Optional[uuid.UUID] = None
    type: str
    uri: str
    version: int = 1
    metadata: Optional[Any] = None


class ArtifactOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_id: Optional[uuid.UUID]
    type: str
    uri: str
    version: int
    metadata: Optional[Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
