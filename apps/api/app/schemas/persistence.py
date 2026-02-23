from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    type: str
    title: str
    body: str
    source: str = "manual"
    created_by: Optional[str] = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    type: str
    version: int
    title: str
    body: str
    source: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "func"
    stage: str = "PLAN"
    status: str = "PENDING"
    assignee: Optional[str] = None
    source: str = "manual"
    document_id: Optional[uuid.UUID] = None
    created_by: Optional[str] = None


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    generated_from_document_version: Optional[int]
    title: str
    description: Optional[str]
    category: str
    stage: str
    status: str
    assignee: Optional[str]
    source: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
