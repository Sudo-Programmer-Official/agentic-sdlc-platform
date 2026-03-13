from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.persistence import RunOut


class RunTimelineSummary(BaseModel):
    goal_text: str | None = None
    status: str
    executor: str
    branch_name: str | None = None
    workspace_status: str
    elapsed_seconds: float | None = None
    recovery_count: int = 0
    artifact_count: int = 0
    changed_files: list[str] = Field(default_factory=list)
    primary_error: str | None = None
    pull_request_url: str | None = None


class RunTimelineStep(BaseModel):
    id: str
    kind: str
    ts: datetime | None = None
    title: str
    status: str
    event_type: str | None = None
    message: str | None = None
    work_item_id: uuid.UUID | None = None
    work_item_type: str | None = None
    work_item_key: str | None = None
    artifact_id: uuid.UUID | None = None
    artifact_type: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    details: dict | None = None


class RunTimelineResponse(BaseModel):
    run: RunOut
    summary: RunTimelineSummary
    steps: list[RunTimelineStep] = Field(default_factory=list)
