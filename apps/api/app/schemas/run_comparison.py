from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RunComparisonArtifact(BaseModel):
    id: uuid.UUID
    type: str
    uri: str
    created_at: datetime
    work_item_id: uuid.UUID | None = None


class RunComparisonSide(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    executor: str
    branch_name: str | None = None
    workspace_status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_seconds: float | None = None
    forked_from_run_id: uuid.UUID | None = None
    recovery_count: int = 0
    recovery_steps: list[str] = Field(default_factory=list)
    artifact_count: int = 0
    artifact_types: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    work_item_counts: dict[str, int] = Field(default_factory=dict)
    pull_request_url: str | None = None
    pull_request_number: int | None = None
    approval_status: str | None = None
    summary: dict | None = None
    artifacts: list[RunComparisonArtifact] = Field(default_factory=list)


class RunComparisonSummary(BaseModel):
    faster_run_id: uuid.UUID | None = None
    faster_by_seconds: float | None = None
    more_recoveries_run_id: uuid.UUID | None = None
    pull_request_run_id: uuid.UUID | None = None
    artifact_types_only_in_a: list[str] = Field(default_factory=list)
    artifact_types_only_in_b: list[str] = Field(default_factory=list)
    files_only_in_a: list[str] = Field(default_factory=list)
    files_only_in_b: list[str] = Field(default_factory=list)


class RunComparisonResponse(BaseModel):
    run_a: RunComparisonSide
    run_b: RunComparisonSide
    summary: RunComparisonSummary
