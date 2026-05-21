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


class MissionControlImportedReference(BaseModel):
    id: uuid.UUID
    type: str
    uri: str
    created_at: datetime
    domain: str | None = None
    label: str | None = None
    imported_at: datetime | None = None
    linked_requirement_id: str | None = None
    linked_run_id: uuid.UUID | None = None
    linked_work_item_id: uuid.UUID | None = None
    linked_task_id: uuid.UUID | None = None
    trust_score: float | None = None
    freshness_score: float | None = None
    used_in_execution_count: int = 0


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
    terminal_quality: str | None = None
    terminal_counts: dict[str, int] = Field(default_factory=dict)


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
    active_preview_url: str | None = None
    stale_preview_url: str | None = None
    preview_domain_host: str | None = None
    preview_domain_url: str | None = None
    frontend_url: str | None = None
    backend_url: str | None = None
    frontend_port: int | None = None
    backend_port: int | None = None
    runtime_classification: str | None = None
    preview_strategy: str | None = None
    active_preview_command: str | None = None
    upstream_preview_port: int | None = None
    frontend_install_status: str | None = None
    backend_install_status: str | None = None
    runtime_boot_duration_seconds: float | None = None
    dependency_repair_attempts: int = 0
    cached_hydration_state: dict[str, object] = Field(default_factory=dict)
    preview_diagnostics: dict[str, object] = Field(default_factory=dict)
    frontend_log_path: str | None = None
    backend_log_path: str | None = None
    preview_checked_at: datetime | None = None
    last_health_check_at: datetime | None = None
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


class MissionControlEtaProfile(BaseModel):
    work_item_type: str
    median_seconds: float
    sample_count: int = 0


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


class MissionControlRunLedgerAggregate(BaseModel):
    total_cost_cents: float = 0.0
    total_duration_ms: int = 0
    recovery_overhead_pct: float = 0.0
    preview_failures: int = 0
    drift_events: int = 0
    targeted_stage_count: int = 0
    component_reuse_ratio: float = 0.0
    module_reuse_ratio: float = 0.0
    avg_reuse_ratio: float = 0.0
    package_drift_count: int = 0
    monolith_risk_max: float = 0.0
    preview_continuity_score: float = 0.0
    avg_targeting_confidence_delta: float = 0.0
    decisive_targeting_count: int = 0
    moderate_targeting_count: int = 0
    close_targeting_count: int = 0


class MissionControlStageLedgerEntry(BaseModel):
    stage_name: str
    lifecycle_state: str
    duration_ms: int | None = None
    retries: int = 0
    recovery_count: int = 0
    model_tier: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_cents: float = 0.0
    files_touched: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    architecture_compliance_score: float | None = None
    package_affinity: str | None = None
    layer_affinity: str | None = None
    topology_zone: str | None = None
    targeting_strategy: str | None = None
    target_file_count: int = 0
    selected_existing_files_count: int = 0
    neighbor_files_count: int = 0
    component_reuse_preferred: bool = False
    module_reuse_preferred: bool = False
    reuse_ratio: float = 0.0
    primary_targeting_reasons: list[str] = Field(default_factory=list)
    primary_target_score: float | None = None
    runner_up_target_score: float | None = None
    targeting_confidence_delta: float | None = None
    targeting_confidence_label: str | None = None
    top_ranked_candidates: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None


class MissionControlExecutionSummary(BaseModel):
    run_id: uuid.UUID
    run_status: str
    workspace_status: str
    current_step: str | None = None
    current_executor: str | None = None
    active_command_count: int = 0
    last_updated_at: datetime | None = None
    execution_contract: MissionControlExecutionContractTelemetry | None = None
    ledger: MissionControlRunLedgerAggregate | None = None


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
    stage_telemetry: list[MissionControlStageLedgerEntry] = Field(default_factory=list)


class MissionControlOverviewResponse(BaseModel):
    work_intake: list[MissionControlWorkIntakeItem] = Field(default_factory=list)
    recent_runs: list[MissionControlRunCard] = Field(default_factory=list)
    latest_change_impact: MissionControlChangeImpact | None = None
    previews_and_prs: MissionControlPreviewAndPrs
    architecture_profile: ArchitectureProfileSummaryOut | None = None
    project_contract: ProjectContractSummaryOut | None = None
    latest_execution_contract: MissionControlExecutionContractTelemetry | None = None
    strategy_learning: list[MissionControlStrategyInsight] = Field(default_factory=list)
    eta_profiles: list[MissionControlEtaProfile] = Field(default_factory=list)
    system_insights: MissionControlSystemInsights
    violation_insights: MissionControlViolationInsights | None = None
    imported_references: list[MissionControlImportedReference] = Field(default_factory=list)
    stalled_runs: list["MissionControlStalledRun"] = Field(default_factory=list)


class MissionControlStalledRun(BaseModel):
    run_id: uuid.UUID
    status: str
    last_event_at: datetime | None = None
    stale_seconds: int = 0
    suggested_action: str = "Inspect run and resume or unblock."


class MissionControlTimelineEvent(BaseModel):
    id: str
    event_at: datetime
    domain: str
    event_type: str
    title: str
    summary: str | None = None
    severity: str = "info"
    status: str = "observed"
    retention_class: str = "keep"
    requirement_id: str | None = None
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    work_item_id: uuid.UUID | None = None
    contract_id: str | None = None
    related_artifact_ids: list[str] = Field(default_factory=list)
    deployment_ref: str | None = None
    metadata: dict | None = None


class MissionControlTimelineResponse(BaseModel):
    items: list[MissionControlTimelineEvent] = Field(default_factory=list)


class MissionControlTimelineBackfillResponse(BaseModel):
    project_id: uuid.UUID
    scanned_limit: int
    before_count: int
    after_count: int
    inserted_count: int


class MissionControlMemorySummaryArtifact(BaseModel):
    id: uuid.UUID
    summary_type: str
    source_entity_type: str
    source_entity_id: str
    version: int
    window_start_at: datetime | None = None
    window_end_at: datetime | None = None
    payload: dict = Field(default_factory=dict)
    quality_score: float | None = None
    created_at: datetime
    updated_at: datetime


class MissionControlMemorySummaryListResponse(BaseModel):
    items: list[MissionControlMemorySummaryArtifact] = Field(default_factory=list)


class MissionControlMemoryExplainResponse(BaseModel):
    target: dict = Field(default_factory=dict)
    top_causes: list[str] = Field(default_factory=list)
    linked_events: list[MissionControlTimelineEvent] = Field(default_factory=list)
    linked_runs: list[str] = Field(default_factory=list)
    linked_requirements: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class MissionControlProjectUnderstandingResponse(BaseModel):
    project_id: str
    summary_artifact_count: int = 0
    major_requirements: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    unstable_validations: list[str] = Field(default_factory=list)
    latest_summaries: dict = Field(default_factory=dict)
