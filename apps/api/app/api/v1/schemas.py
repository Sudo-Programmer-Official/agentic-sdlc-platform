from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

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
    architecture_refresh_needed: bool = False
    plan_refresh_needed: bool = False
    test_refresh_needed: bool = False


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
    executor: Optional[str] = None
    goal_text: Optional[str] = None
    branch_name: Optional[str] = None
    workspace_status: Optional[str] = None
    recovery_count: int = 0
    artifact_count: int = 0
    files_changed: List[str] = Field(default_factory=list)
    primary_error: Optional[str] = None
    approval_status: Optional[str] = None
    pull_request_url: Optional[str] = None
    pull_request_number: Optional[int] = None
    delivery_pushed: bool = False
    delivery_branch_name: Optional[str] = None
    delivery_commit_sha: Optional[str] = None
    delivery_pushed_at: Optional[str] = None


class CreateRunRequest(BaseModel):
    stage: Optional[str] = None


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
    architecture_refresh_needed: bool = False
    plan_refresh_needed: bool = False
    test_refresh_needed: bool = False
    requirements_status: Optional[str] = None
    requirements_version: Optional[int] = None
    requirements_sha: Optional[str] = None
    plan_exists: bool = False
    plan_fresh: bool = False
    plan_id: Optional[str] = None
    plan_requirements_sha: Optional[str] = None
    plan_created_at: Optional[str] = None


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
    linked_requirements: list[str] = Field(default_factory=list)
    plan_id: str | None = None
    plan_version: int | None = None
    parent_task_id: str | None = None
    superseded_by: str | None = None
    deprecated: bool = False
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


# Requirements engine schemas
class PRDIngestRequest(BaseModel):
    text: str
    format: str = Field(default="markdown")
    source: str = Field(default="typed")


class RequirementNodeModel(BaseModel):
    id: str
    type: str
    text: str
    confidence: float = 0.8
    source: str = "human"
    quality_type: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class RequirementEdgeModel(BaseModel):
    id: Optional[str] = None
    from_id: str
    to_id: str
    relation: str = "constrains"
    weight: float = 0.5
    rationale: Optional[str] = None


class RequirementGraphModel(BaseModel):
    project_id: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    nodes: List[RequirementNodeModel]
    edges: List[RequirementEdgeModel]


class RequirementGraphUpdateRequest(BaseModel):
    nodes: List[RequirementNodeModel]
    edges: List[RequirementEdgeModel]


class RequirementGraphApproveRequest(BaseModel):
    approved_by: str


class RequirementGraphApproveResponse(BaseModel):
    project_id: str
    version: int
    sha256: str
    status: str


class PlanRegenerateRequest(BaseModel):
    triggered_by: str = "system"
    mode: str = "AUTO"  # AUTO|FULL|PARTIAL


class PlanRegenerateResponse(BaseModel):
    plan_path: str
    created_at: str
    plan_id: str
    requirements_sha: str | None = None
    raw: str
    regeneration_mode: str
    reused_task_ids: list[str] = []
    regenerated_task_ids: list[str] = []
    changed_requirements: list[str] = []


class PlanHistoryEntry(BaseModel):
    version: int
    plan_id: str
    requirements_sha: str | None = None
    created_at: str
    triggered_by: str
    plan_path: str
    regeneration_mode: str
    changed_requirements_count: int
    reused_count: int
    regenerated_count: int


class PlanHistoryResponse(BaseModel):
    project_id: str
    entries: list[PlanHistoryEntry]
