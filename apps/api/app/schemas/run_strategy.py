from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RunStrategyPlanRequest(BaseModel):
    goal: str | None = None
    error: str | None = None
    files: list[str] = Field(default_factory=list)
    executor: str | None = None
    start_now: bool = True
    limit: int = 3
    mode: str | None = None
    feedback_text: str | None = None
    feedback_source: str | None = None


class RunStrategyCandidate(BaseModel):
    run_id: uuid.UUID
    status: str
    executor: str
    branch_name: str | None = None
    strategy_type: str
    label: str
    rationale: str
    prompt_hint: str | None = None
    score: float | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    pull_request_url: str | None = None
    created_at: datetime | None = None


class RunStrategyRecommendation(BaseModel):
    run_id: uuid.UUID
    strategy_type: str
    label: str
    score: float
    rationale: list[str] = Field(default_factory=list)


class RunStrategyGroupResponse(BaseModel):
    group_id: uuid.UUID
    source_run_id: uuid.UUID
    project_id: uuid.UUID
    goal: str | None = None
    error: str | None = None
    files: list[str] = Field(default_factory=list)
    candidates: list[RunStrategyCandidate] = Field(default_factory=list)
    recommendation: RunStrategyRecommendation | None = None
