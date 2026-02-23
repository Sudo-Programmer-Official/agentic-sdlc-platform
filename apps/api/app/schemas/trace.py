from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TraceCreate(BaseModel):
    from_type: str
    from_id: uuid.UUID
    to_type: str
    to_id: uuid.UUID
    relation_type: str = "relates"
    relation_strength: float = 1.0


class TraceOut(BaseModel):
    id: uuid.UUID
    from_type: str
    from_id: uuid.UUID
    to_type: str
    to_id: uuid.UUID
    relation_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
