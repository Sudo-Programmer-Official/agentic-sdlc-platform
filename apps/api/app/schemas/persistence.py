from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


TaskBranchStrategy = Literal["auto", "new", "existing"]


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
    body: str = Field(validation_alias=AliasChoices("body", "content"))
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
    source_type: str = "manual"
    source_node_id: Optional[str] = None
    requirement_id: Optional[str] = None
    derived_from_requirement_ids: list[str] = Field(default_factory=list)
    capability_id: Optional[str] = None
    capability_label: Optional[str] = None
    architecture_slice: Optional[str] = None
    impact_zone: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
    document_id: Optional[uuid.UUID] = None
    created_by: Optional[str] = None
    branch_strategy: TaskBranchStrategy = "auto"
    base_branch: Optional[str] = None
    branch_name: Optional[str] = None

    @field_validator("branch_strategy", mode="before")
    @classmethod
    def normalize_branch_strategy(cls, value: str | None) -> str:
        return (value or "auto").strip().lower()

    @field_validator("base_branch", "branch_name", mode="before")
    @classmethod
    def normalize_branch_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_branch_settings(self) -> "TaskCreate":
        if self.branch_strategy == "auto":
            self.base_branch = None
            self.branch_name = None
            return self

        if not self.branch_name:
            raise ValueError("branch_name is required when branch_strategy is 'new' or 'existing'")

        if self.branch_strategy == "existing":
            self.base_branch = None

        return self


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
    source_type: str = "manual"
    source_node_id: Optional[str] = None
    requirement_id: Optional[str] = None
    derived_from_requirement_ids: Optional[list[str]] = None
    capability_id: Optional[str] = None
    capability_label: Optional[str] = None
    architecture_slice: Optional[str] = None
    impact_zone: Optional[list[str]] = None
    provenance: Optional[dict] = None
    rerun_of_task_id: Optional[uuid.UUID] = None
    created_by: Optional[str]
    branch_strategy: TaskBranchStrategy = "auto"
    base_branch: Optional[str]
    branch_name: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ImprovementRequestOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    source_run_id: uuid.UUID
    source_requirement_id: Optional[str] = None
    strategy_group_id: Optional[uuid.UUID] = None
    goal_text: Optional[str] = None
    issue_text: Optional[str] = None
    files: list[str] = Field(default_factory=list)
    executor: Optional[str] = None
    feedback_source: Optional[str] = None
    start_now: bool = True
    status: str
    created_run_ids: list[uuid.UUID] = Field(default_factory=list)
    resulting_run_id: Optional[uuid.UUID] = None
    resulting_pr_url: Optional[str] = None
    resolution_status: Optional[str] = None
    resolution_summary: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RequirementTaskCountsOut(BaseModel):
    total: int = 0
    open: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    rerun_pending: int = 0


class RequirementRunCountsOut(BaseModel):
    total: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0


class RequirementImprovementCountsOut(BaseModel):
    total: int = 0
    open: int = 0
    resolved: int = 0


class RequirementSummaryCardOut(BaseModel):
    requirement_id: str
    title: str
    status: str
    priority: str
    task_counts: RequirementTaskCountsOut
    run_counts: RequirementRunCountsOut
    improvement_counts: RequirementImprovementCountsOut
    last_activity_at: datetime | None = None
    health_score: int
    risk_level: str
    stability_score: int = 100
    retry_count: int = 0
    unresolved_count: int = 0
    recurring_failure_patterns: list[str] = Field(default_factory=list)
    most_impacted_modules: list[str] = Field(default_factory=list)
    ai_spend_cents: float = 0.0
    ai_total_tokens: int = 0


class RequirementSummaryResponse(BaseModel):
    items: list[RequirementSummaryCardOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    next_offset: int | None = None


class RequirementTimelineEventOut(BaseModel):
    type: str
    title: str
    description: str | None = None
    source_type: str
    source_id: str
    status: str | None = None
    created_at: datetime


class RequirementTimelineResponse(BaseModel):
    items: list[RequirementTimelineEventOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0
    next_offset: int | None = None


class RequirementExecutionGraphOut(BaseModel):
    requirement_id: str
    tasks: list[TaskOut] = Field(default_factory=list)
    runs: list[RunOut] = Field(default_factory=list)
    improvements: list[ImprovementRequestOut] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
    pull_requests: list[dict] = Field(default_factory=list)
    deploys: list[dict] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    related_modules: list[str] = Field(default_factory=list)


class RequirementRelationshipCreate(BaseModel):
    from_requirement_id: str
    to_requirement_id: str
    relation_type: str
    rationale: Optional[str] = None
    created_by: Optional[str] = None


class RequirementRelationshipOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    from_requirement_id: str
    to_requirement_id: str
    relation_type: str
    rationale: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FoundationReadinessCheckOut(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class FoundationReadinessOut(BaseModel):
    status: str
    mode: str
    repo_connected: bool
    architecture_profile_present: bool
    checks: list[FoundationReadinessCheckOut] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    recommended_next_step: str


class ProjectBlueprintCreate(BaseModel):
    blueprint_key: str = "fullstack_monorepo"
    stack_preset_key: str = "vue_fastapi"
    deployment_profile: str = "local_preview"
    readiness_enforced: bool = True
    created_by: Optional[str] = None


class StackPresetOut(BaseModel):
    key: str
    label: str
    runtime: str
    config_json: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ProjectBlueprintOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    blueprint_key: str
    stack_preset_key: str
    deployment_profile: str
    architecture: str
    status: str
    readiness_enforced: bool
    generated_modules: list[str] = Field(default_factory=list)
    generated_contracts: list[str] = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectTopologySnapshotOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    blueprint_id: Optional[uuid.UUID] = None
    version: int
    topology_json: dict = Field(default_factory=dict)
    summary: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectGenesisRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    blueprint_id: Optional[uuid.UUID] = None
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_task_ids: list[str] = Field(default_factory=list)
    validation: dict = Field(default_factory=dict)
    summary: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectGenesisLaunchOut(BaseModel):
    blueprint: ProjectBlueprintOut
    topology_snapshot: ProjectTopologySnapshotOut
    genesis_run: ProjectGenesisRunOut


class GovernanceKpiSampleSizesOut(BaseModel):
    genesis_runs: int = 0
    topology_snapshots: int = 0
    feature_runs: int = 0
    ai_jobs: int = 0


class GovernanceKpisOut(BaseModel):
    project_id: str
    blueprint_present: bool = False
    genesis_success_rate: float = 0.0
    deterministic_replay_match: float = 0.0
    feature_runs_without_genesis: int = 0
    context_pack_usage: float = 0.0
    context_efficiency_ratio: float = 0.0
    context_loaded_count: int = 0
    context_selected_count: int = 0
    sample_sizes: GovernanceKpiSampleSizesOut


class RunImpactScoreOut(BaseModel):
    run_id: uuid.UUID
    predicted_files: list[str] = Field(default_factory=list)
    actual_files_changed: list[str] = Field(default_factory=list)
    overlap_files: list[str] = Field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    recovery_count: int = 0
    regression_signals: list[str] = Field(default_factory=list)


class RunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    executor: str
    workspace_root: Optional[str] = None
    repo_path: Optional[str] = None
    branch_name: Optional[str] = None
    requirement_id: Optional[str] = None
    workspace_status: str = "PENDING"
    workspace_error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[dict] = None
    allowed_transitions: list[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    executor: str = "codex"
    task_id: Optional[uuid.UUID] = None
    run_kind: str | None = None


class VisionRunScreenshotIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = "image/png"
    data_base64: str = Field(min_length=1)


class VisionRunCreate(BaseModel):
    project_id: uuid.UUID
    goal_text: str = Field(min_length=1, max_length=4000)
    screenshots: list[VisionRunScreenshotIn] = Field(default_factory=list)
    page_url: Optional[str] = None
    preferred_executor: str = "codex"
    auto_start: bool = True
    auto_deploy: bool = False
    metadata: dict = Field(default_factory=dict)


class VisionRunOut(BaseModel):
    task_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    status_url: str
    source_type: str


class ProjectRepositoryConnect(BaseModel):
    provider: str = "github"
    repo_url: str
    repo_full_name: Optional[str] = None
    default_branch: str = "main"
    installation_id: Optional[int] = None
    auth_strategy: str = "runtime_default"
    created_by: Optional[str] = None


class ProjectRepositoryPreflightRequest(BaseModel):
    provider: str = "github"
    repo_url: Optional[str] = None
    repo_full_name: Optional[str] = None
    default_branch: Optional[str] = None
    installation_id: Optional[int] = None
    auth_strategy: Optional[str] = None
    clone: bool = True


class ProjectRepositoryPreflightOut(BaseModel):
    ok: bool
    provider: str
    auth_strategy: str
    auth_mode: Optional[str] = None
    credential_strategy: Optional[str] = None
    selection_reason: Optional[str] = None
    transport_url: Optional[str] = None
    repo_url: str
    default_branch: str
    installation_id: Optional[int] = None
    token_generated: bool = False
    git_binary: Optional[str] = None
    error: Optional[str] = None


class ProjectRepositoryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    repo_url: str
    repo_full_name: Optional[str]
    default_branch: str
    installation_id: Optional[int]
    auth_strategy: str = "runtime_default"
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GitHubConnectInfoOut(BaseModel):
    enabled: bool
    app_slug: Optional[str] = None
    allowed_org: Optional[str] = None
    install_url: Optional[str] = None
    runtime_git_auth_mode: str = "auto"


class GitHubInstallationRepositoryOut(BaseModel):
    id: int
    name: str
    full_name: str
    clone_url: Optional[str] = None
    ssh_url: Optional[str] = None
    html_url: Optional[str] = None
    default_branch: str = "main"
    private: bool = False
    owner_login: Optional[str] = None


class PullRequestCreate(BaseModel):
    artifact_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    body: Optional[str] = None
    branch_name: Optional[str] = None


class PullRequestOut(BaseModel):
    run_id: uuid.UUID
    artifact_id: uuid.UUID
    pull_request_url: Optional[str]
    pull_request_number: Optional[int]
    branch_name: str
    base_branch: str
    commit_sha: str


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
    status: Literal["DONE", "SKIPPED"] = "DONE"
    result: dict = Field(default_factory=dict)
    artifacts: list[dict] = Field(default_factory=list)


class WorkItemFail(BaseModel):
    error: str
    retry: bool = False


class ExternalReferenceIngestRequest(BaseModel):
    url: str
    label: Optional[str] = None
    run_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    work_item_id: Optional[uuid.UUID] = None
    requirement_id: Optional[str] = None


class ExternalReferenceOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    work_item_id: Optional[uuid.UUID] = None
    requirement_id: Optional[str] = None
    type: str
    uri: str
    metadata: dict = Field(default_factory=dict, validation_alias=AliasChoices("metadata", "extra_metadata"))
    created_at: datetime
