from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RunMemoryMatch(BaseModel):
    run_id: uuid.UUID
    status: str
    executor: str
    branch_name: str | None = None
    goal: str | None = None
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    elapsed_seconds: float | None = None
    recovery_count: int = 0
    files_changed: list[str] = Field(default_factory=list)
    artifact_types: list[str] = Field(default_factory=list)
    pull_request_url: str | None = None
    last_error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class RunMemoryResponse(BaseModel):
    query: dict[str, object]
    matches: list[RunMemoryMatch] = Field(default_factory=list)
