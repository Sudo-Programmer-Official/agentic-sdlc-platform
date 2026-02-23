from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ApprovalCreate(BaseModel):
    target_type: str  # document|task|artifact
    target_id: uuid.UUID
    status: str = "PENDING"
    decided_by: Optional[str] = None
    comment: Optional[str] = None


class ApprovalOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    comment: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
