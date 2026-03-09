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
    allowed_transitions: list[str] = []
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
    run_id: Optional[uuid.UUID] = None
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


class RunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    executor: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[dict] = None
    allowed_transitions: list[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    executor: str = "dummy"


class WorkItemOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    type: str
    key: Optional[str] = None
    status: str
    priority: int
    executor: str
    assigned_agent_id: Optional[uuid.UUID] = None
    attempt: int
    max_attempts: int
    depends_on_count: int
    lease_expires_at: Optional[datetime] = None
    required_capabilities: list = Field(default_factory=list)
    payload: dict
    result: dict
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkItemEdgeOut(BaseModel):
    from_work_item_id: uuid.UUID
    to_work_item_id: uuid.UUID


class AgentCreate(BaseModel):
    name: str
    kind: str
    executors: list[str] = Field(default_factory=list)
    max_concurrency: int = 1
    capabilities: dict = Field(default_factory=dict)


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    executors: list[str]
    capabilities: dict
    max_concurrency: int
    status: str
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkItemComplete(BaseModel):
    result: dict = Field(default_factory=dict)
    artifacts: list[dict] = Field(default_factory=list)


class WorkItemFail(BaseModel):
    error: str
    retry: bool = False
