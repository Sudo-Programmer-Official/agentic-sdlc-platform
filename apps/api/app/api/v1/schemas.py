from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None


class AdvanceStageRequest(BaseModel):
    to_stage: str


class RequestApprovalRequest(BaseModel):
    stage: str
    requested_by: str
    comment: Optional[str] = None


class DecideApprovalRequest(BaseModel):
    decision: str
    decided_by: str
    comment: Optional[str] = None


class TriggerAgentRunRequest(BaseModel):
    project_id: str
    stage: str
    agent_name: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    current_stage: str
    created_at: datetime


class TransitionResponse(BaseModel):
    project: ProjectResponse
    from_stage: str
    to_stage: str


class ApprovalResponse(BaseModel):
    id: str
    project_id: str
    stage: str
    status: str
    requested_by: str
    requested_at: datetime
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: Optional[str] = None


class RunResponse(BaseModel):
    run_id: str
    project_id: str
    stage: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RunSummary(BaseModel):
    run_id: str
    status: str
    stage: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class TaskCounts(BaseModel):
    pending: int
    running: int
    done: int
    failed: int
    canceled: int


class ProjectSummaryResponse(BaseModel):
    project_id: str
    name: str
    current_stage: str
    latest_run: Optional[RunSummary] = None
    task_counts: TaskCounts


class ProjectMetricsResponse(BaseModel):
    total_runs: int
    active_runs: int
    stale_count: int
    open_changes: int


class RunMetricsResponse(BaseModel):
    run_id: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    tasks_total: int
    tasks_pending: int
    tasks_running: int
    tasks_done: int
    tasks_failed: int
    tasks_canceled: int
    avg_task_duration_seconds: Optional[float] = None
    retries: int
    agent_distribution: Dict[str, int]


class ChangeRequestCreate(BaseModel):
    source: str
    summary: str
    affected_area: str
    severity: str
    suggested_stage: str


class ChangeRequestDecision(BaseModel):
    decided_by: Optional[str] = None


class ChangeRequestResponse(BaseModel):
    id: str
    project_id: str
    source: str
    summary: str
    affected_area: str
    severity: str
    suggested_stage: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    run_id: str
    agent: str
    title: str
    status: str
    depends_on: list[str]
    parallel_group: str
    outputs: list[str]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class AuditLogResponse(BaseModel):
    timestamp: datetime
    run_id: str
    stage: str
    agent: str
    tool: str
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class StatusResponse(BaseModel):
    status: str
    message: Optional[str] = None
