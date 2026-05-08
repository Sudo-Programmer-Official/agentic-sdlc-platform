from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.architecture_profile import ArchitectureProfileSummaryOut
from app.schemas.project_contract import ProjectContractSummaryOut


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
    execution_contract: MissionControlExecutionContractTelemetry | None = None


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
    run_id: uuid.UUID | None = None
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


class MissionControlViolationSample(BaseModel):
    run_id: uuid.UUID
    work_item_id: uuid.UUID | None = None
    work_item_type: str | None = None
    mode: str = "off"
    blocking: bool = False
    type: str = "project_contract_violation"
    rule: str = "unknown"
    file: str | None = None
    value: str | None = None
    message: str | None = None


class MissionControlViolationInsights(BaseModel):
    latest_run_id: uuid.UUID | None = None
    latest_run_total: int = 0
    latest_run_blocking: int = 0
    latest_run_warning: int = 0
    recent_run_window: int = 5
    recent_total: int = 0
    top_rules: list[MissionControlNamedCount] = Field(default_factory=list)
    top_types: list[MissionControlNamedCount] = Field(default_factory=list)
    top_files: list[MissionControlNamedCount] = Field(default_factory=list)
    recent_samples: list[MissionControlViolationSample] = Field(default_factory=list)


class MissionControlExecutionEnvironment(BaseModel):
    workspace_root: str | None = None
    repo_path: str | None = None
    artifacts_path: str | None = None
    logs_path: str | None = None
    patches_path: str | None = None
    branch_name: str | None = None
    workspace_status: str | None = None
    repo_seeded: bool = False
    repo_url: str | None = None
    repo_branch: str | None = None
    repo_auth_mode: str | None = None
    simulation_mode: str | None = None
    cleanup_policy: str | None = None
    command_audit_log: str | None = None
    workspace_manifest_path: str | None = None
    allowed_command_prefixes: list[str] = Field(default_factory=list)
    runtime_mode: str | None = None
    runtime_git_auth_mode: str | None = None
    runtime_git_auth_status: str | None = None
    runtime_git_auth_ready: bool = False
    runtime_git_auth_missing: list[str] = Field(default_factory=list)
    git_binary: str | None = None
    ssh_binary: str | None = None
    github_clone_auth_status: str | None = None
    github_clone_auth_ready: bool = False
    github_clone_auth_missing: list[str] = Field(default_factory=list)
    github_app_id_present: bool = False
    github_private_key_present: bool = False
    github_webhook_secret_present: bool = False


class MissionControlExecutionCommand(BaseModel):
    command_id: str
    label: str
    status: str
    command: list[str] = Field(default_factory=list)
    cwd: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    timed_out: bool = False
    blocked_reason: str | None = None
    log_path: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None


class MissionControlExecutionStep(BaseModel):
    work_item_id: uuid.UUID
    title: str
    type: str
    executor: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt: int = 0
    summary: str | None = None


class MissionControlExecutionSummary(BaseModel):
    run_id: uuid.UUID
    run_status: str
    workspace_status: str
    current_step: str | None = None
    current_executor: str | None = None
    active_command_count: int = 0
    last_updated_at: datetime | None = None
    execution_contract: MissionControlExecutionContractTelemetry | None = None


class MissionControlExecutionBudgetTelemetry(BaseModel):
    max_tokens: int = 0
    used_tokens: int = 0
    remaining_tokens: int = 0
    max_cost_cents: float = 0.0
    used_cost_cents: float = 0.0
    remaining_cost_cents: float = 0.0
    recovery_reserve_cost_cents: float = 0.0
    used_recovery_cost_cents: float = 0.0
    remaining_recovery_cost_cents: float = 0.0
    active_budget_partition: str = "main"
    budget_mode: str = "NORMAL"
    model_tier_cap: str | None = None
    completion_token_cap: int | None = None
    escalation_reason: str | None = None
    last_model_tier: str | None = None
    updated_at: datetime | None = None


class MissionControlExecutionContractTelemetry(BaseModel):
    lifecycle_state: str
    validation_state: str
    retry_state: str
    scope_mode: str
    risk_level: str
    file_budget: int
    hard_file_budget: int
    target_files: list[str] = Field(default_factory=list)
    allowed_file_count: int = 0
    protected_paths: list[str] = Field(default_factory=list)
    safe_paths: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    allowed_command_prefixes: list[str] = Field(default_factory=list)
    build_command: str | None = None
    test_command: str | None = None
    lint_command: str | None = None
    budget: MissionControlExecutionBudgetTelemetry


class MissionControlExecutionConsoleResponse(BaseModel):
    summary: MissionControlExecutionSummary
    environment: MissionControlExecutionEnvironment
    commands: list[MissionControlExecutionCommand] = Field(default_factory=list)
    steps: list[MissionControlExecutionStep] = Field(default_factory=list)


class MissionControlOverviewResponse(BaseModel):
    work_intake: list[MissionControlWorkIntakeItem] = Field(default_factory=list)
    recent_runs: list[MissionControlRunCard] = Field(default_factory=list)
    latest_change_impact: MissionControlChangeImpact | None = None
    previews_and_prs: MissionControlPreviewAndPrs
    architecture_profile: ArchitectureProfileSummaryOut | None = None
    project_contract: ProjectContractSummaryOut | None = None
    latest_execution_contract: MissionControlExecutionContractTelemetry | None = None
    strategy_learning: list[MissionControlStrategyInsight] = Field(default_factory=list)
    system_insights: MissionControlSystemInsights
    violation_insights: MissionControlViolationInsights | None = None
