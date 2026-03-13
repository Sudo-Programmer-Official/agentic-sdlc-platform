from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MissionControlArtifactRef(BaseModel):
    id: uuid.UUID
    type: str
    uri: str
    created_at: datetime


class MissionControlWorkIntakeItem(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    source: str | None = None
    summary: str | None = None
    created_at: datetime
    predicted_modules: list[str] = Field(default_factory=list)
    predicted_files: list[str] = Field(default_factory=list)
    risk_tier: str = "LOW"
    confidence_score: float = 0.0
    suggested_plan: list[str] = Field(default_factory=list)
    related_task_count: int = 0


class MissionControlRunCard(BaseModel):
    run_id: uuid.UUID
    goal_text: str | None = None
    status: str
    executor: str
    branch_name: str | None = None
    elapsed_seconds: float | None = None
    recovery_count: int = 0
    artifact_count: int = 0
    files_changed: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    pull_request_url: str | None = None
    approval_status: str | None = None
    created_at: datetime
    patch_artifact: MissionControlArtifactRef | None = None


class MissionControlChangeImpact(BaseModel):
    run_id: uuid.UUID | None = None
    files_changed: list[str] = Field(default_factory=list)
    modules_impacted: list[str] = Field(default_factory=list)
    tests_impacted: list[str] = Field(default_factory=list)
    api_impact: list[str] = Field(default_factory=list)
    risk_score: float = 0.0
    risk_tier: str = "LOW"
    confidence_score: float = 0.0
    additions: int = 0
    deletions: int = 0
    approval_status: str | None = None
    patch_artifact: MissionControlArtifactRef | None = None
    pull_request_url: str | None = None


class MissionControlPreviewAndPrs(BaseModel):
    repository_connected: bool = False
    profile_configured: bool = False
    provider: str | None = None
    repo_full_name: str | None = None
    branch_name: str | None = None
    preview_mode: str | None = None
    preview_status: str = "NOT_CONFIGURED"
    preview_url: str | None = None
    frontend_url: str | None = None
    backend_url: str | None = None
    frontend_log_path: str | None = None
    backend_log_path: str | None = None
    preview_expires_at: datetime | None = None
    requires_verification: bool = False
    verification_note: str | None = None
    patch_artifact: MissionControlArtifactRef | None = None
    pull_request_url: str | None = None
    approval_status: str | None = None
    file_count: int = 0
    additions: int = 0
    deletions: int = 0


class MissionControlStrategyInsight(BaseModel):
    strategy_type: str
    label: str
    uses: int
    success_rate: float
    average_elapsed_seconds: float | None = None


class MissionControlNamedCount(BaseModel):
    name: str
    count: int


class MissionControlSystemInsights(BaseModel):
    total_runs: int = 0
    successful_runs: int = 0
    success_rate: float = 0.0
    average_fix_time_seconds: float | None = None
    total_pull_requests: int = 0
    average_recovery_count: float = 0.0
    most_impacted_modules: list[MissionControlNamedCount] = Field(default_factory=list)
    most_impacted_files: list[MissionControlNamedCount] = Field(default_factory=list)


class MissionControlOverviewResponse(BaseModel):
    work_intake: list[MissionControlWorkIntakeItem] = Field(default_factory=list)
    recent_runs: list[MissionControlRunCard] = Field(default_factory=list)
    latest_change_impact: MissionControlChangeImpact | None = None
    previews_and_prs: MissionControlPreviewAndPrs
    strategy_learning: list[MissionControlStrategyInsight] = Field(default_factory=list)
    system_insights: MissionControlSystemInsights
