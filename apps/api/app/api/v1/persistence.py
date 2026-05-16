from __future__ import annotations

import base64
import binascii
import csv
import io
import logging
import uuid
from urllib.parse import quote_plus
from datetime import date, datetime, timezone, timedelta
from collections import defaultdict
from types import SimpleNamespace
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, and_, exists, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Project,
    Document,
    Task,
    Run,
    RunSummary as RunSummaryModel,
    RunEvent,
    WorkItem,
    WorkItemEdge,
    Agent,
    Artifact,
    ProjectRepository,
    ProjectPreviewProfile,
    ProjectDeployment,
    DeploymentProfile,
    DeploymentProviderConnector,
    ImprovementRequest,
    RequirementMemory,
    RequirementRelationship,
    ProjectBlueprint,
    ProjectGenesisRun,
    ProjectTopologySnapshot,
    StackPreset,
    ActivityLog,
    Workspace,
    Tenant,
    TenantMember,
    WorkspaceMember,
    WorkspaceEntitlement,
    WorkspaceUsageDaily,
    WorkspaceAnomalySnapshot,
    EnvironmentChecklist,
    PlatformConfig,
    WorkspaceSecret,
    ProjectEnvironmentVariable,
    EnvironmentValidationResult,
    EnvironmentSyncStatus,
    AdminAuditLog,
    ImpersonationSession,
)
from app.db.session import get_session
from app.schemas.persistence import (
    ProjectCreate,
    ProjectOut,
    DocumentCreate,
    DocumentOut,
    TaskCreate,
    TaskOut,
    RunOut,
    RunCreate,
    ProjectRepositoryConnect,
    ProjectRepositoryOut,
    ProjectRepositoryPreflightRequest,
    ProjectRepositoryPreflightOut,
    FoundationReadinessOut,
    GitHubConnectInfoOut,
    GitHubInstallationRepositoryOut,
    PullRequestCreate,
    PullRequestOut,
    WorkItemOut,
    WorkItemEdgeOut,
    AgentCreate,
    AgentOut,
    WorkItemComplete,
    WorkItemFail,
    VisionRunCreate,
    VisionRunOut,
    ImprovementRequestOut,
    RequirementSummaryResponse,
    RequirementTimelineResponse,
    RequirementExecutionGraphOut,
    RequirementRelationshipCreate,
    RequirementRelationshipOut,
    ProjectBlueprintCreate,
    ProjectBlueprintOut,
    ProjectGenesisLaunchOut,
    ProjectGenesisRunOut,
    ProjectTopologySnapshotOut,
    StackPresetOut,
    GovernanceKpisOut,
    RunImpactScoreOut,
    ExternalReferenceIngestRequest,
    ExternalReferenceOut,
)
from app.services import github_adapter
from app.schemas.run_comparison import RunComparisonResponse
from app.schemas.run_memory import RunMemoryResponse
from app.schemas.run_narrative import RunNarrativeResponse
from app.schemas.run_strategy import RunStrategyGroupResponse, RunStrategyPlanRequest
from app.schemas.run_timeline import RunTimelineResponse
from app.schemas.preview import (
    ProjectPreviewProfileOut,
    ProjectPreviewProfileUpsert,
    RunPreviewLaunchRequest,
    RunPreviewOut,
)
from app.services.activity_log import log_activity
from app.services.event_log import record_event
from app.services.runtime_lineage import persist_work_item_artifacts
from app.services.state_guard import update_run_status as guarded_update_run_status, update_work_item_status
from app.runtime.leases import DEFAULT_CLAIM_LEASE_SECONDS
from app.runtime.orchestrator import RunOrchestrator
from app.runtime.recovery_policy import maybe_apply_recovery
from app.runtime.recovery_policy import has_pending_recovery_work, sync_run_recovery_latch
from app.db.session import SessionLocal
from app.services.run_replay import fork_run
from app.services.repo_connector import connect_repo, get_project_repository, preflight_repo_access
from app.services.foundation_readiness import build_foundation_readiness
from app.services.project_genesis import (
    ensure_stack_presets,
    get_latest_genesis_run,
    get_latest_topology_snapshot,
    get_project_blueprint,
    run_project_genesis,
)
from app.services.task_lineage import add_task_lineage_traces
from app.services.pr_service import create_pr_from_artifact
from app.services.preview_service import (
    DEFAULT_STATIC_START_COMMAND,
    get_project_preview_profile,
    get_run_preview,
    launch_run_preview,
    stop_run_preview,
    upsert_project_preview_profile,
)
from app.services.run_comparison import compare_runs
from app.services.run_memory import find_similar_runs
from app.services.run_narrative import build_run_narrative
from app.services.run_launch import _schedule_orchestrator_start, launch_run_for_project
from app.services.run_delivery import publish_run_branch_if_ready
from app.services.run_resume import prepare_run_for_resume
from app.services.strategy_selection import create_strategy_group, get_strategy_group
from app.services.run_timeline import build_run_timeline
from app.services.workspace_supervisor import ensure_run_workspace, destroy_run_workspace
from app.services.work_item_state import is_dependency_satisfied
from app.services.requirements_bridge import ensure_legacy_project, load_requirements_plan_state
from app.services.run_summary_builder import ensure_project_run_summaries
from app.services.architecture_profile_service import (
    bootstrap_architecture_profile,
    derive_architecture_profile,
    summarize_architecture_profile,
)
from app.services.requirement_tracking import build_requirement_summary, build_requirement_timeline
from app.services.requirement_execution_graph import build_requirement_execution_graph
from app.services.requirement_memory import compress_requirement_memory
from app.services.project_contract_service import summarize_project_contract
from app.services.governance_kpis import build_governance_kpis
from app.services.impact_analysis_loop import score_impact_prediction
from app.services.external_reference_ingestion import persist_external_reference
from app.services.secret_vault import resolve_vault_secret, store_vault_secret
from app.services.environment_readiness import (
    checklist_template,
    complete_timestamp,
    infer_item_status,
    normalize_missing_prerequisites,
    summarize_rows,
)
from app.services.deployment_readiness import compute_deployment_readiness
from app.runtime.execution_contract import coerce_execution_contract, sync_run_execution_contract_state
from app.api.v1.schemas import (
    ProjectSummaryResponse,
    TaskCounts,
    ProjectMetricsResponse,
    PlanHistoryResponse,
    RunSummary,
)
from app.core.config import get_settings
from app.api.deps import get_tenant_context, get_tenant_id, ZERO_TENANT
from app.services.firebase_auth import FirebaseAuthError, verify_firebase_bearer_token


# Legacy store prefix (DB-backed) and public projects prefix to align with UI.
router = APIRouter(prefix="/store", tags=["store"])
public_router = APIRouter(tags=["projects"])
settings = get_settings()
log = logging.getLogger("app.persistence")

ENVIRONMENT_TEMPLATES: dict[str, dict] = {
    "vue_fastapi": {
        "name": "Vue + FastAPI",
        "description": "Vue frontend with FastAPI backend and common service credentials.",
        "deployment_targets": ["vercel", "render"],
        "provider_mappings": {"vercel": "frontend", "render": "backend"},
        "variables": [
            {"key": "VITE_API_BASE_URL", "required": True, "scope": "frontend"},
            {"key": "API_BASE_URL", "required": True, "scope": "backend"},
            {"key": "DATABASE_URL", "required": True, "scope": "backend"},
            {"key": "JWT_SECRET", "required": True, "scope": "backend"},
            {"key": "OPENAI_API_KEY", "required": False, "scope": "backend"},
        ],
    },
    "nextjs_supabase": {
        "name": "Next.js + Supabase",
        "description": "Next.js app with Supabase auth and database.",
        "deployment_targets": ["vercel"],
        "provider_mappings": {"vercel": "fullstack"},
        "variables": [
            {"key": "NEXT_PUBLIC_SUPABASE_URL", "required": True, "scope": "frontend"},
            {"key": "NEXT_PUBLIC_SUPABASE_ANON_KEY", "required": True, "scope": "frontend"},
            {"key": "SUPABASE_SERVICE_ROLE_KEY", "required": True, "scope": "backend"},
            {"key": "DATABASE_URL", "required": True, "scope": "backend"},
            {"key": "NEXTAUTH_SECRET", "required": True, "scope": "backend"},
        ],
    },
    "firebase_saas": {
        "name": "Firebase SaaS",
        "description": "Firebase-auth SaaS baseline with database and billing optionals.",
        "deployment_targets": ["vercel", "render"],
        "provider_mappings": {"vercel": "frontend", "render": "backend"},
        "variables": [
            {"key": "VITE_FIREBASE_API_KEY", "required": True, "scope": "frontend"},
            {"key": "VITE_FIREBASE_AUTH_DOMAIN", "required": True, "scope": "frontend"},
            {"key": "FIREBASE_PROJECT_ID", "required": True, "scope": "shared"},
            {"key": "DATABASE_URL", "required": True, "scope": "backend"},
            {"key": "STRIPE_SECRET_KEY", "required": False, "scope": "backend"},
            {"key": "OPENAI_API_KEY", "required": False, "scope": "backend"},
        ],
    },
    "mern": {
        "name": "MERN",
        "description": "MongoDB, Express, React, Node deployment baseline.",
        "deployment_targets": ["render", "vercel"],
        "provider_mappings": {"vercel": "frontend", "render": "backend"},
        "variables": [
            {"key": "MONGODB_URI", "required": True, "scope": "backend"},
            {"key": "JWT_SECRET", "required": True, "scope": "backend"},
            {"key": "CORS_ORIGIN", "required": True, "scope": "backend"},
            {"key": "VITE_API_BASE_URL", "required": True, "scope": "frontend"},
        ],
    },
    "static_marketing_site": {
        "name": "Static Marketing Site",
        "description": "Static site with optional analytics and lead capture integrations.",
        "deployment_targets": ["vercel"],
        "provider_mappings": {"vercel": "frontend"},
        "variables": [
            {"key": "VITE_SITE_URL", "required": True, "scope": "frontend"},
            {"key": "VITE_ANALYTICS_ID", "required": False, "scope": "frontend"},
            {"key": "FORM_WEBHOOK_URL", "required": False, "scope": "shared"},
        ],
    },
}


class StageUpdate(BaseModel):
    to_stage: str


class RunResumeRequest(BaseModel):
    start_now: bool = True


class RunRetryPushRequest(BaseModel):
    auth_strategy: str | None = None


class RunUnblockResponse(BaseModel):
    run_id: uuid.UUID
    run_status: str
    nudged: bool
    nudged_agent_ids: list[str] = Field(default_factory=list)
    queued_before: int
    runnable_before: int
    active_before: int
    queued_after: int
    runnable_after: int
    active_after: int
    detail: str


class RunDiscardResponse(BaseModel):
    run_id: uuid.UUID
    run_status: str
    preview_status: str | None = None
    workspace_deleted: bool
    workspace_root: str | None = None
    detail: str


class ProjectDeploymentCreateRequest(BaseModel):
    provider: str = "vercel"
    environment: str = "PREVIEW"
    deployment_strategy: str = "static_frontend"
    target: str = "user_app"
    run_id: uuid.UUID | None = None
    request_key: str | None = None
    repository_url: str | None = None
    repository_full_name: str | None = None
    branch_name: str | None = None
    created_by: str | None = None
    env_overrides: dict[str, str] | None = None
    integration_mode: str | None = None


class ProjectDeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID | None = None
    provider: str
    environment: str
    deployment_strategy: str
    target: str
    status: str
    request_key: str | None = None
    external_deployment_id: str | None = None
    deployment_url: str | None = None
    dashboard_url: str | None = None
    error_message: str | None = None
    deployment_confidence_score: float = 0.0
    rollback_source_deployment_id: uuid.UUID | None = None
    rollback_reason: str | None = None
    rollback_trigger: str | None = None
    promoted_from_environment: str | None = None
    extra_metadata: dict | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectDeploymentRetryRequest(BaseModel):
    force: bool = False


class ProjectDeploymentPromoteRequest(BaseModel):
    target_environment: str
    reason: str | None = None
    request_key: str | None = None
    created_by: str | None = None


class ProjectDeploymentRollbackRequest(BaseModel):
    reason: str | None = None
    trigger: str = "manual"
    request_key: str | None = None
    created_by: str | None = None


class ProjectDeploymentPreflightRequest(BaseModel):
    provider: str
    environment: str = "PREVIEW"
    deployment_strategy: str = "static_frontend"
    repository_url: str | None = None
    repository_full_name: str | None = None
    branch_name: str | None = None


class DeploymentEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action_type: str
    event_type: str | None = None
    actor: str | None = None
    extra_metadata: dict | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    created_at: datetime


class WorkspaceSwitchOut(BaseModel):
    workspace: WorkspaceOut
    projects: list[ProjectOut] = Field(default_factory=list)


class WorkspaceEntitlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    plan: str
    limits: dict = Field(default_factory=dict)
    features: dict = Field(default_factory=dict)
    effective_from: datetime
    updated_at: datetime


class AdminWorkspaceEntitlementPatchRequest(BaseModel):
    plan: str | None = None
    limits: dict | None = None
    features: dict | None = None


class WorkspaceUsageDailyOut(BaseModel):
    usage_date: str
    runs_count: int = 0
    deployments_count: int = 0
    recoveries_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_cents: int = 0


class WorkspaceUsageSummaryOut(BaseModel):
    workspace_id: uuid.UUID
    days: int
    totals: WorkspaceUsageDailyOut
    daily: list[WorkspaceUsageDailyOut] = Field(default_factory=list)


class EnvironmentChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID
    environment: str
    item_key: str
    label: str
    owner: str
    status: str
    required: bool
    category: str | None = None
    note: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class EnvironmentChecklistEnvironmentSummaryOut(BaseModel):
    environment: str
    total: int
    completed: int
    platform_total: int
    platform_completed: int
    user_pending: int
    score_pct: int


class EnvironmentChecklistSummaryOut(BaseModel):
    project_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    score_pct: int
    total: int
    completed: int
    environments: list[EnvironmentChecklistEnvironmentSummaryOut] = Field(default_factory=list)
    items: list[EnvironmentChecklistItemOut] = Field(default_factory=list)


class AdminWorkspaceOut(BaseModel):
    workspace: WorkspaceOut
    project_count: int = 0
    run_count_7d: int = 0
    failed_run_count_7d: int = 0


class AdminImpersonationStartRequest(BaseModel):
    workspace_id: uuid.UUID
    reason: str | None = None
    duration_minutes: int = Field(default=30, ge=5, le=240)


class AdminImpersonationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admin_user_id: str
    target_workspace_id: uuid.UUID
    reason: str | None = None
    started_at: datetime
    expires_at: datetime | None = None
    ended_at: datetime | None = None
    is_active: bool
    ended_by: str | None = None
    action_count: int


class AdminAuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admin_user_id: str
    target_workspace_id: uuid.UUID | None = None
    action: str
    reason: str | None = None
    duration_seconds: int | None = None
    extra_metadata: dict | None = None
    created_at: datetime


class AdminDaemonHealthOut(BaseModel):
    last_cycle_at: datetime | None = None
    last_cycle_window_days: int | None = None
    last_cycle_workspaces_processed: int = 0
    last_cycle_workspace_failures: int = 0
    last_error_at: datetime | None = None
    last_error_workspace_id: uuid.UUID | None = None
    alert_level: str = "healthy"
    alert_reasons: list[str] = Field(default_factory=list)


class PlatformConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    config_key: str
    config_scope: str
    value_type: str
    vault_ref: str | None = None
    has_plain_value: bool = False
    description: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PlatformConfigUpsertRequest(BaseModel):
    value_type: str = "string"
    plain_value: str | None = None
    vault_ref: str | None = None
    description: str | None = None
    reason: str | None = None


class PlatformConfigRotateRequest(BaseModel):
    vault_ref: str
    reason: str | None = None


class ProjectEnvironmentVariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    project_id: uuid.UUID
    environment: str
    var_key: str
    value_kind: str
    has_value: bool = False
    required: bool
    source: str | None = None
    validation_regex: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectEnvironmentVariableUpsertRequest(BaseModel):
    value_kind: str = "secret"
    plain_value: str | None = None
    vault_ref: str | None = None
    required: bool = True
    source: str | None = None
    validation_regex: str | None = None


class EnvironmentSecretWriteRequest(BaseModel):
    value: str


class EnvironmentValidateRequest(BaseModel):
    checks: list[str] = Field(default_factory=list)
    reason: str | None = None


class EnvironmentSyncRequest(BaseModel):
    reason: str | None = None


class EnvironmentValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    environment: str
    check_key: str
    status: str
    message: str | None = None
    checked_at: datetime


class EnvironmentSyncStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    environment: str
    provider: str
    status: str
    message: str | None = None
    drift_detected: bool
    last_synced_at: datetime | None = None
    updated_at: datetime


class ProjectEnvironmentProfileOut(BaseModel):
    environment: str
    variables_configured: int
    variables_total: int
    validation_passed: int
    validation_total: int
    sync_healthy: int
    sync_total: int


class ProjectEnvironmentCenterOut(BaseModel):
    project_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    environments: list[ProjectEnvironmentProfileOut] = Field(default_factory=list)


class EnvironmentTemplateVarOut(BaseModel):
    key: str
    required: bool = True
    scope: str = "shared"
    source: str = "template"
    validation_regex: str | None = None


class EnvironmentTemplateOut(BaseModel):
    key: str
    name: str
    description: str
    deployment_targets: list[str] = Field(default_factory=list)
    provider_mappings: dict[str, str] = Field(default_factory=dict)
    variables: list[EnvironmentTemplateVarOut] = Field(default_factory=list)


class EnvironmentTemplateApplyRequest(BaseModel):
    environment: str
    include_optional: bool = True


class DeploymentReadinessContractOut(BaseModel):
    project_id: uuid.UUID
    environment: str
    score_pct: int
    safe_to_preview: bool
    safe_to_production: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    categories: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class WorkspaceUsageMaterializeOut(BaseModel):
    workspace_id: uuid.UUID
    days: int
    rows_upserted: int = 0
    totals: WorkspaceUsageDailyOut


class WorkspaceAnomalySnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    snapshot_date: date
    window_days: int
    runs_count: int = 0
    recoveries_count: int = 0
    total_tokens: int = 0
    total_cost_cents: int = 0
    burn_spike: bool = False
    failure_spike: bool = False
    burn_ratio: str | None = None
    failure_ratio: str | None = None
    created_at: datetime
    updated_at: datetime


class FirstLoginBootstrapRequest(BaseModel):
    tenant_name: str | None = None
    workspace_name: str | None = None
    force_new_tenant: bool = False


class FirstLoginBootstrapOut(BaseModel):
    user_id: str
    tenant_id: uuid.UUID
    tenant_name: str
    workspace_id: uuid.UUID
    workspace_name: str
    tenant_member_role: str
    workspace_member_role: str
    created_tenant: bool = False
    created_workspace: bool = False
    created_tenant_member: bool = False
    created_workspace_member: bool = False


class DeploymentIntelligenceOut(BaseModel):
    project_id: uuid.UUID
    total_deployments: int = 0
    success_rate: float = 0.0
    avg_confidence: float = 0.0
    top_failure_clusters: list[dict] = Field(default_factory=list)
    confidence_trend: list[dict] = Field(default_factory=list)
    recent_manual_degrade_reasons: list[str] = Field(default_factory=list)


class DeploymentProfileUpsertRequest(BaseModel):
    environment: str = "PREVIEW"
    provider: str = "vercel"
    deployment_strategy: str = "static_frontend"
    framework: str | None = None
    install_command: str | None = None
    build_command: str | None = None
    output_dir: str | None = None
    start_command: str | None = None
    healthcheck_path: str | None = "/"
    region: str | None = None
    runtime_version: str | None = None
    env_schema: dict | None = None
    provider_connector_id: uuid.UUID | None = None
    created_by: str | None = None


class DeploymentProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    environment: str
    provider: str
    deployment_strategy: str
    framework: str | None = None
    install_command: str | None = None
    build_command: str | None = None
    output_dir: str | None = None
    start_command: str | None = None
    healthcheck_path: str | None = None
    region: str | None = None
    runtime_version: str | None = None
    env_schema: dict | None = None
    provider_connector_id: uuid.UUID | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class DeploymentProviderConnectorUpsertRequest(BaseModel):
    provider: str
    label: str
    vault_ref: str
    scopes: dict | None = None
    created_by: str | None = None


class DeploymentProviderConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: str
    label: str
    vault_ref: str
    scopes: dict | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


ALLOWED_TRANSITIONS = {
    "INTAKE": {"PLAN"},
    "PLAN": {"RUN"},
    "RUN": {"EVALUATE"},
    "EVALUATE": set(),
}

RUN_ALLOWED = {
    "QUEUED": {"RUNNING"},
    "RUNNING": {"COMPLETED", "FAILED", "CANCELED", "PAUSED"},
    "PAUSED": {"QUEUED", "RUNNING", "CANCELED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELED": set(),
}

ACTIVE_RUN_STATUSES = ("RUNNING", "QUEUED")


def _run_activity_ordering():
    return (
        case(
            (Run.status == "RUNNING", 0),
            (Run.status == "QUEUED", 1),
            else_=2,
        ),
        func.coalesce(Run.started_at, Run.created_at, Run.updated_at).desc(),
        Run.id.desc(),
    )


def _allowed_for(status: str) -> list[str]:
    return sorted(ALLOWED_TRANSITIONS.get(status.upper(), set()))


def _project_out(project: Project) -> ProjectOut:
    data = ProjectOut.model_validate(project)
    data.allowed_transitions = _allowed_for(project.status)
    return data


def _run_out(run: Run) -> RunOut:
    data = RunOut.model_validate(run)
    data.allowed_transitions = sorted(RUN_ALLOWED.get(run.status, set()))
    return data


def _task_out(task: Task) -> TaskOut:
    data = TaskOut.model_validate(task)
    provenance = task.provenance if isinstance(task.provenance, dict) else {}
    rerun_ref = provenance.get("rerun_of_task_id") or provenance.get("parent_task_id") or provenance.get("supersedes_task_id")
    if isinstance(rerun_ref, str):
        try:
            data.rerun_of_task_id = uuid.UUID(rerun_ref)
        except ValueError:
            data.rerun_of_task_id = None
    return data


def _improvement_request_out(request: ImprovementRequest) -> ImprovementRequestOut:
    data = ImprovementRequestOut.model_validate(request)
    created_run_ids: list[uuid.UUID] = []
    for value in request.created_run_ids or []:
        try:
            created_run_ids.append(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    data.created_run_ids = created_run_ids
    files = request.files if isinstance(request.files, list) else []
    data.files = [value for value in files if isinstance(value, str)]
    return data


def _delivery_summary_value(summary: dict | None, key: str) -> str | None:
    if not isinstance(summary, dict):
        return None
    value = summary.get(key)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _wi_out(wi: WorkItem) -> WorkItemOut:
    return WorkItemOut.model_validate(wi)


def _project_repo_out(repo: ProjectRepository) -> ProjectRepositoryOut:
    return ProjectRepositoryOut.model_validate(repo)


def _project_preview_profile_out(profile: ProjectPreviewProfile) -> ProjectPreviewProfileOut:
    return ProjectPreviewProfileOut.model_validate(profile)


def _external_reference_out(artifact: Artifact) -> ExternalReferenceOut:
    return ExternalReferenceOut(
        id=artifact.id,
        project_id=artifact.project_id,
        run_id=artifact.run_id,
        task_id=artifact.task_id,
        work_item_id=artifact.work_item_id,
        requirement_id=artifact.requirement_id,
        type=artifact.type,
        uri=artifact.uri,
        metadata=artifact.extra_metadata or {},
        created_at=artifact.created_at,
    )


def _vision_task_title(goal_text: str) -> str:
    head = " ".join(goal_text.strip().split())
    if not head:
        return "Vision-guided UI update"
    return head[:120]


def _vision_task_prompt(goal_text: str) -> str:
    cleaned_goal = " ".join(goal_text.strip().split())
    if not cleaned_goal:
        return "Use the attached screenshot and implement the requested UI update with scoped, minimal changes."
    return f"User goal: {cleaned_goal}"


def _project_scope_filters(ctx) -> list:
    filters = [Project.tenant_id == ctx.tenant_id]
    if getattr(ctx, "workspace_id", None):
        # Backward compatibility: legacy projects without workspace_id remain accessible.
        filters.append(or_(Project.workspace_id == ctx.workspace_id, Project.workspace_id.is_(None)))
    return filters


def _project_scoped(session: AsyncSession, ctx, project_id: uuid.UUID):
    return select(Project).where(Project.id == project_id, *_project_scope_filters(ctx))


def _run_scoped(session: AsyncSession, ctx, run_id: uuid.UUID):
    return (
        select(Run)
        .join(Project, Project.id == Run.project_id)
        .where(Run.id == run_id, Run.tenant_id == ctx.tenant_id, *_project_scope_filters(ctx))
    )


def _default_workspace_limits() -> dict:
    return {
        "projects": 5,
        "monthly_tokens": 500000,
        "deployments_per_month": 20,
    }


def _default_workspace_features() -> dict:
    return {
        "preview_deployments": True,
        "production_deployments": False,
        "recovery_memory": True,
        "workspace_connectors": True,
    }


async def _ensure_workspace_entitlement(session: AsyncSession, ctx, workspace_id: uuid.UUID) -> WorkspaceEntitlement:
    entitlement = await session.scalar(
        select(WorkspaceEntitlement).where(
            WorkspaceEntitlement.tenant_id == ctx.tenant_id,
            WorkspaceEntitlement.workspace_id == workspace_id,
        )
    )
    if entitlement is not None:
        return entitlement
    entitlement = WorkspaceEntitlement(
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        plan="starter",
        limits=_default_workspace_limits(),
        features=_default_workspace_features(),
    )
    session.add(entitlement)
    await session.flush()
    await session.commit()
    await session.refresh(entitlement)
    return entitlement


def _is_super_admin(ctx) -> bool:
    current_settings = get_settings()
    allowed = [item.strip() for item in (current_settings.super_admin_users or "").split(",") if item.strip()]
    return bool(ctx.user_id and ctx.user_id in allowed)


def _extract_bearer_token_or_401(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_MISSING", "message": "Authorization bearer token is required."},
        )
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Authorization header must use Bearer token."},
        )
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Authorization bearer token is required."},
        )
    return token


def _user_id_from_claims(claims: dict) -> str:
    for key in ("user_id", "uid", "sub", "email"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "system"


def _sanitize_entity_name(value: str | None, fallback: str, *, max_len: int = 180) -> str:
    text = (value or "").strip()
    if not text:
        text = fallback
    text = " ".join(text.split())
    return text[:max_len] if len(text) > max_len else text


def _platform_config_out(row: PlatformConfig) -> PlatformConfigOut:
    return PlatformConfigOut(
        id=row.id,
        config_key=row.config_key,
        config_scope=row.config_scope,
        value_type=row.value_type,
        vault_ref=row.vault_ref,
        has_plain_value=bool((row.plain_value or "").strip()),
        description=row.description,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _project_env_var_out(row: ProjectEnvironmentVariable) -> ProjectEnvironmentVariableOut:
    has_value = bool((row.vault_ref or "").strip()) or bool((row.plain_value or "").strip())
    return ProjectEnvironmentVariableOut(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        environment=row.environment,
        var_key=row.var_key,
        value_kind=row.value_kind,
        has_value=has_value,
        required=row.required,
        source=row.source,
        validation_regex=row.validation_regex,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _entitlement_enforcement_mode() -> tuple[bool, bool]:
    current = get_settings()
    return bool(current.workspace_entitlements_enabled), bool(current.workspace_entitlements_enforce)


def _as_int_limit(value, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else default
    except Exception:
        return default


async def _check_workspace_project_limit(session: AsyncSession, ctx, workspace_id: uuid.UUID) -> None:
    enabled, enforce = _entitlement_enforcement_mode()
    if not enabled:
        return
    entitlement = await _ensure_workspace_entitlement(session, ctx, workspace_id)
    project_limit = _as_int_limit((entitlement.limits or {}).get("projects"), 0)
    if project_limit <= 0:
        return
    current_count = await session.scalar(
        select(func.count(Project.id)).where(
            Project.tenant_id == ctx.tenant_id,
            Project.workspace_id == workspace_id,
        )
    ) or 0
    if current_count < project_limit:
        return
    message = f"Workspace project limit reached ({current_count}/{project_limit})."
    if enforce:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    log.warning("ENTITLEMENT_WARN project_limit workspace_id=%s tenant_id=%s current=%s limit=%s", workspace_id, ctx.tenant_id, current_count, project_limit)


async def _check_workspace_deployment_limit(session: AsyncSession, ctx, workspace_id: uuid.UUID) -> None:
    enabled, enforce = _entitlement_enforcement_mode()
    if not enabled:
        return
    entitlement = await _ensure_workspace_entitlement(session, ctx, workspace_id)
    deployment_limit = _as_int_limit((entitlement.limits or {}).get("deployments_per_month"), 0)
    if deployment_limit <= 0:
        return
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    project_ids = (
        await session.execute(
            select(Project.id).where(Project.tenant_id == ctx.tenant_id, Project.workspace_id == workspace_id)
        )
    ).scalars().all()
    if not project_ids:
        return
    current_count = await session.scalar(
        select(func.count(ProjectDeployment.id)).where(
            ProjectDeployment.tenant_id == ctx.tenant_id,
            ProjectDeployment.project_id.in_(project_ids),
            ProjectDeployment.created_at >= month_start,
        )
    ) or 0
    if current_count < deployment_limit:
        return
    message = f"Workspace deployment monthly limit reached ({current_count}/{deployment_limit})."
    if enforce:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    log.warning("ENTITLEMENT_WARN deployment_limit workspace_id=%s tenant_id=%s current=%s limit=%s", workspace_id, ctx.tenant_id, current_count, deployment_limit)


async def _check_workspace_token_limit(session: AsyncSession, ctx, workspace_id: uuid.UUID) -> None:
    enabled, enforce = _entitlement_enforcement_mode()
    if not enabled:
        return
    entitlement = await _ensure_workspace_entitlement(session, ctx, workspace_id)
    token_limit = _as_int_limit((entitlement.limits or {}).get("monthly_tokens"), 0)
    if token_limit <= 0:
        return
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    project_ids = (
        await session.execute(
            select(Project.id).where(Project.tenant_id == ctx.tenant_id, Project.workspace_id == workspace_id)
        )
    ).scalars().all()
    if not project_ids:
        return
    run_rows = (
        await session.execute(
            select(Run.summary).where(
                Run.tenant_id == ctx.tenant_id,
                Run.project_id.in_(project_ids),
                Run.created_at >= month_start,
            )
        )
    ).scalars().all()
    consumed = 0
    for summary in run_rows:
        if not isinstance(summary, dict):
            continue
        usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
        consumed += int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    if consumed < token_limit:
        return
    message = f"Workspace monthly token limit reached ({consumed}/{token_limit})."
    if enforce:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    log.warning("ENTITLEMENT_WARN token_limit workspace_id=%s tenant_id=%s current=%s limit=%s", workspace_id, ctx.tenant_id, consumed, token_limit)


async def _load_workspace_usage_summary(
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    days: int,
) -> WorkspaceUsageSummaryOut:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    project_ids = (
        await session.execute(
            select(Project.id).where(
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
            )
        )
    ).scalars().all()

    run_rows = []
    if project_ids:
        run_rows = (
            await session.execute(
                select(Run.id, Run.created_at, Run.summary)
                .where(
                    Run.tenant_id == tenant_id,
                    Run.project_id.in_(project_ids),
                    Run.created_at >= since,
                )
            )
        ).all()

    deployment_rows = []
    if project_ids:
        deployment_rows = (
            await session.execute(
                select(ProjectDeployment.created_at, ProjectDeployment.status)
                .where(
                    ProjectDeployment.tenant_id == tenant_id,
                    ProjectDeployment.project_id.in_(project_ids),
                    ProjectDeployment.created_at >= since,
                )
            )
        ).all()

    token_by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "total_cost_cents": 0})
    recoveries_by_day: dict[str, int] = defaultdict(int)
    for row in run_rows:
        day = row.created_at.date().isoformat()
        summary = row.summary if isinstance(row.summary, dict) else {}
        usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
        token_by_day[day]["input_tokens"] += int(usage.get("input_tokens") or 0)
        token_by_day[day]["output_tokens"] += int(usage.get("output_tokens") or 0)
        token_by_day[day]["total_cost_cents"] += int(round(float(usage.get("actual_cost_cents") or 0)))
        if summary.get("resume_state") or summary.get("last_resume_checkpoint_id") or summary.get("recovery"):
            recoveries_by_day[day] += 1

    runs_by_day: dict[str, int] = defaultdict(int)
    for row in run_rows:
        runs_by_day[row.created_at.date().isoformat()] += 1

    deployments_by_day: dict[str, int] = defaultdict(int)
    for row in deployment_rows:
        deployments_by_day[row.created_at.date().isoformat()] += 1

    daily: list[WorkspaceUsageDailyOut] = []
    totals = WorkspaceUsageDailyOut(usage_date="total")
    for offset in range(days - 1, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).date().isoformat()
        usage_bucket = token_by_day[day]
        row = WorkspaceUsageDailyOut(
            usage_date=day,
            runs_count=runs_by_day[day],
            deployments_count=deployments_by_day[day],
            recoveries_count=recoveries_by_day[day],
            input_tokens=usage_bucket["input_tokens"],
            output_tokens=usage_bucket["output_tokens"],
            total_cost_cents=usage_bucket["total_cost_cents"],
        )
        daily.append(row)
        totals.runs_count += row.runs_count
        totals.deployments_count += row.deployments_count
        totals.recoveries_count += row.recoveries_count
        totals.input_tokens += row.input_tokens
        totals.output_tokens += row.output_tokens
        totals.total_cost_cents += row.total_cost_cents

    return WorkspaceUsageSummaryOut(
        workspace_id=workspace_id,
        days=days,
        totals=totals,
        daily=daily,
    )


async def _seed_environment_checklists_for_project(
    session: AsyncSession,
    *,
    ctx,
    project: Project,
) -> list[EnvironmentChecklist]:
    existing = (
        await session.execute(
            select(EnvironmentChecklist).where(
                EnvironmentChecklist.tenant_id == ctx.tenant_id,
                EnvironmentChecklist.project_id == project.id,
            )
        )
    ).scalars().all()
    existing_map = {(row.environment, row.item_key): row for row in existing}
    has_repo = await session.scalar(
        select(exists().where(ProjectRepository.tenant_id == ctx.tenant_id, ProjectRepository.project_id == project.id))
    )
    has_connector = await session.scalar(
        select(exists().where(DeploymentProviderConnector.tenant_id == ctx.tenant_id))
    )
    preview_ready = await session.scalar(
        select(exists().where(Run.tenant_id == ctx.tenant_id, Run.project_id == project.id, Run.status == "COMPLETED"))
    )
    readiness = await build_foundation_readiness(session, tenant_id=ctx.tenant_id, project_id=project.id)
    missing = normalize_missing_prerequisites((readiness or {}).get("missing_prerequisites"))

    touched: list[EnvironmentChecklist] = []
    for template in checklist_template():
        status_value, note_value = infer_item_status(
            template,
            has_repo=bool(has_repo),
            has_connector=bool(has_connector),
            preview_ready=bool(preview_ready),
            foundation_missing=missing,
        )
        key = (template.environment, template.item_key)
        row = existing_map.get(key)
        if row is None:
            row = EnvironmentChecklist(
                tenant_id=ctx.tenant_id,
                workspace_id=project.workspace_id or ctx.workspace_id,
                project_id=project.id,
                environment=template.environment,
                item_key=template.item_key,
                label=template.label,
                owner=template.owner,
                status=status_value,
                required=template.required,
                category=template.category,
                note=note_value or template.note,
                completed_at=complete_timestamp(status_value),
                extra_metadata={"seed_source": "environment_readiness_v1"},
            )
            session.add(row)
        else:
            row.workspace_id = project.workspace_id or row.workspace_id or ctx.workspace_id
            row.label = template.label
            row.owner = template.owner
            row.required = template.required
            row.category = template.category
            row.status = status_value
            row.note = note_value or template.note
            row.completed_at = complete_timestamp(status_value)
        touched.append(row)

    await session.flush()
    return touched


async def _load_environment_checklists(
    session: AsyncSession,
    *,
    ctx,
    project: Project,
    reseed: bool = True,
) -> EnvironmentChecklistSummaryOut:
    if reseed:
        await _seed_environment_checklists_for_project(session, ctx=ctx, project=project)
        await session.commit()

    rows = (
        await session.execute(
            select(EnvironmentChecklist)
            .where(EnvironmentChecklist.tenant_id == ctx.tenant_id, EnvironmentChecklist.project_id == project.id)
            .order_by(EnvironmentChecklist.environment.asc(), EnvironmentChecklist.owner.asc(), EnvironmentChecklist.item_key.asc())
        )
    ).scalars().all()
    summary = summarize_rows(rows)
    return EnvironmentChecklistSummaryOut(
        project_id=project.id,
        workspace_id=project.workspace_id,
        score_pct=summary["score_pct"],
        total=summary["total"],
        completed=summary["completed"],
        environments=[EnvironmentChecklistEnvironmentSummaryOut(**env) for env in summary["environments"]],
        items=[EnvironmentChecklistItemOut.model_validate(row) for row in rows],
    )


def _compute_usage_anomaly_flags(daily: list[WorkspaceUsageDailyOut]) -> tuple[bool, bool, str | None, str | None]:
    if len(daily) < 4:
        return False, False, None, None
    midpoint = max(1, len(daily) // 2)
    prior = daily[:midpoint]
    recent = daily[midpoint:]
    prior_tokens = sum((row.input_tokens or 0) + (row.output_tokens or 0) for row in prior)
    recent_tokens = sum((row.input_tokens or 0) + (row.output_tokens or 0) for row in recent)
    prior_runs = max(1, sum(row.runs_count or 0 for row in prior))
    recent_runs = max(1, sum(row.runs_count or 0 for row in recent))
    prior_recoveries = sum(row.recoveries_count or 0 for row in prior)
    recent_recoveries = sum(row.recoveries_count or 0 for row in recent)
    prior_recovery_rate = prior_recoveries / prior_runs
    recent_recovery_rate = recent_recoveries / recent_runs
    burn_ratio_value = (recent_tokens / prior_tokens) if prior_tokens > 0 else (2.0 if recent_tokens > 0 else 1.0)
    failure_ratio_value = (
        (recent_recovery_rate / prior_recovery_rate)
        if prior_recovery_rate > 0
        else (2.0 if recent_recovery_rate > 0 else 1.0)
    )
    burn_spike = recent_tokens > prior_tokens * 1.5 and recent_tokens - prior_tokens > 1000
    failure_spike = recent_recovery_rate > prior_recovery_rate * 1.5 and recent_recoveries >= 2
    return burn_spike, failure_spike, f"{burn_ratio_value:.2f}", f"{failure_ratio_value:.2f}"


def _wi_scoped(session: AsyncSession, ctx, wi_id: uuid.UUID):
    return select(WorkItem).where(WorkItem.id == wi_id, WorkItem.tenant_id == ctx.tenant_id)


async def _find_run_by_request_key(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    request_key: str,
    source_run_id: uuid.UUID | None = None,
) -> Run | None:
    if not request_key:
        return None
    rows = (
        await session.execute(
            select(Run)
            .where(Run.tenant_id == tenant_id, Run.project_id == project_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(200)
        )
    ).scalars().all()
    for row in rows:
        summary = row.summary if isinstance(row.summary, dict) else {}
        if str(summary.get("request_key") or "").strip() != request_key:
            continue
        if source_run_id is not None and str(summary.get("fork_source_run_id") or "").strip() != str(source_run_id):
            continue
        return row
    return None


async def _maybe_finalize_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    run = await session.get(Run, run_id)
    if not run or run.status in {"COMPLETED", "FAILED", "CANCELED"}:
        return
    recovery_pending = await has_pending_recovery_work(session, run_id)
    if recovery_pending:
        await sync_run_recovery_latch(session, run_id)
        return
    counts = (
        await session.execute(
            select(
                func.count().filter(WorkItem.status.in_(["RUNNING", "CLAIMED"])),
                func.count().filter(WorkItem.status == "QUEUED"),
            ).where(WorkItem.run_id == run_id)
        )
    ).first()
    active, queued = counts
    failed_results = (
        await session.execute(
            select(WorkItem.result).where(
                WorkItem.run_id == run_id,
                WorkItem.status == "FAILED",
            )
        )
    ).scalars().all()
    failed = sum(
        1
        for result in failed_results
        if not (isinstance(result, dict) and result.get("superseded") is True)
    )
    if failed and active == 0 and queued == 0:
        run.status = "FAILED"
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_FAILED",
            actor_type="SYSTEM",
        )
    elif failed == 0 and active == 0 and queued == 0:
        run.status = "COMPLETED"
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_COMPLETED",
            actor_type="SYSTEM",
        )
        try:
            from app.services import knowledge_service

            # Keep optional knowledge ingestion from poisoning the main transaction.
            async with session.begin_nested():
                await knowledge_service.ingest_agent_run_event(session, run_id=run.id, actor_id="system")
        except Exception:
            pass
    else:
        return
    # Recompute lifecycle on finalization
    try:
        from app.api.v1.lifecycle_score import lifecycle_score

        await lifecycle_score(project_id=run.project_id, session=session)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="LIFECYCLE_SCORED",
            actor_type="SYSTEM",
        )
    except Exception:
        pass


async def _runnable_queued_items_for_run(session: AsyncSession, run_id: uuid.UUID) -> list[WorkItem]:
    queued_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run_id, WorkItem.status == "QUEUED")
            .order_by(WorkItem.priority.desc(), WorkItem.created_at)
        )
    ).scalars().all()
    if not queued_items:
        return []
    queued_ids = [item.id for item in queued_items]
    parent = WorkItem
    dependency_rows = (
        await session.execute(
            select(
                WorkItemEdge.to_work_item_id,
                parent.status,
                parent.payload,
                parent.result,
            )
            .join(parent, parent.id == WorkItemEdge.from_work_item_id)
            .where(
                WorkItemEdge.run_id == run_id,
                WorkItemEdge.to_work_item_id.in_(queued_ids),
            )
        )
    ).all()
    deps_by_child: dict = {}
    for to_work_item_id, status, payload, result_payload in dependency_rows:
        deps_by_child.setdefault(to_work_item_id, []).append(
            SimpleNamespace(status=status, payload=payload, result=result_payload)
        )
    return [
        item
        for item in queued_items
        if all(is_dependency_satisfied(dep) for dep in deps_by_child.get(item.id, []))
    ]
@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    if ctx.enforcement and ctx.tenant_id == ZERO_TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="system tenant is read-only")
    if ctx.workspace_id:
        await _check_workspace_project_limit(session, ctx, ctx.workspace_id)
    project = Project(
        name=payload.name,
        description=payload.description,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
    )
    session.add(project)
    await session.flush()
    if payload.starter_blueprint_enabled:
        try:
            await run_project_genesis(
                session,
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                blueprint_key=payload.starter_blueprint_key,
                stack_preset_key=payload.starter_stack_preset_key,
                deployment_profile=payload.starter_deployment_profile,
                readiness_enforced=True,
                created_by=getattr(ctx, "user_id", None),
            )
            await bootstrap_architecture_profile(
                session,
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                refresh_repo_map_requested=False,
                created_by=getattr(ctx, "user_id", None),
            )
            await derive_architecture_profile(
                session,
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                refresh_repo_map_requested=False,
                bootstrap_if_missing=True,
                updated_by=getattr(ctx, "user_id", None),
            )
        except ValueError:
            # Fallback-safe: project creation should still succeed even when starter provisioning fails.
            pass
    await log_activity(
        session,
        project_id=project.id,
        entity_type="project",
        entity_id=project.id,
        action_type="project.created",
        metadata={"name": payload.name},
    )
    await session.commit()
    await session.refresh(project)
    return _project_out(project)


@router.get("/projects", response_model=List[ProjectOut])
@public_router.get("/projects", response_model=List[ProjectOut])
async def list_projects(
    ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)
) -> List[ProjectOut]:
    result = await session.execute(
        select(Project).where(*_project_scope_filters(ctx)).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return [_project_out(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
@public_router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    project = await session.scalar(select(Project).where(Project.id == project_id, *_project_scope_filters(ctx)))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return _project_out(project)


@router.post("/tasks/vision-run", response_model=VisionRunOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/tasks/vision-run", response_model=VisionRunOut, status_code=status.HTTP_201_CREATED)
async def create_vision_run(
    payload: VisionRunCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> VisionRunOut:
    project = await session.scalar(
        _project_scoped(session, ctx, payload.project_id)
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    screenshot_summaries: list[dict] = []
    for index, screenshot in enumerate(payload.screenshots, start=1):
        try:
            raw = base64.b64decode(screenshot.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64 in screenshots[{index - 1}]",
            ) from exc
        screenshot_summaries.append(
            {
                "index": index,
                "filename": screenshot.filename,
                "content_type": screenshot.content_type,
                "bytes": len(raw),
            }
        )

    metadata_payload = payload.metadata if isinstance(payload.metadata, dict) else {}
    task = Task(
        tenant_id=ctx.tenant_id,
        project_id=project.id,
        title=_vision_task_title(payload.goal_text),
        description=_vision_task_prompt(payload.goal_text),
        category="ui",
        stage="PLAN",
        status="PENDING",
        source="vision",
        source_type="screenshot_guided_edit",
        provenance={
            **metadata_payload,
            "page_url": payload.page_url,
            "auto_deploy": payload.auto_deploy,
            "visual_intent": payload.goal_text.strip(),
            "screenshot_count": len(payload.screenshots),
            "screenshots": screenshot_summaries,
            "vision_intake_v1": True,
        },
        created_by=ctx.user_id,
        branch_strategy="auto",
    )
    session.add(task)
    await session.flush()

    executor_name = (payload.preferred_executor or "codex").strip().lower() or "codex"
    try:
        run = await launch_run_for_project(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project.id,
            executor_name=executor_name,
            task_id=task.id,
            actor_type="USER",
            schedule=payload.auto_start,
        )
    except ValueError as exc:
        detail = str(exc)
        lowered = detail.lower()
        if "installation is required" in lowered or "github app installation" in lowered:
            code = status.HTTP_400_BAD_REQUEST
        else:
            code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=detail) from exc

    for index, screenshot in enumerate(payload.screenshots, start=1):
        session.add(
            Artifact(
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                task_id=task.id,
                run_id=run.id,
                type="screenshot_input",
                uri=f"inline://vision-inputs/{task.id}/{index:02d}-{screenshot.filename}",
                version=1,
                extra_metadata={
                    "filename": screenshot.filename,
                    "content_type": screenshot.content_type,
                    "data_base64": screenshot.data_base64,
                    "index": index,
                    "source_type": "screenshot_guided_edit",
                    "page_url": payload.page_url,
                },
            )
        )

    await log_activity(
        session,
        project_id=project.id,
        entity_type="task",
        entity_id=task.id,
        action_type="task.vision_run.created",
        metadata={
            "run_id": str(run.id),
            "executor": executor_name,
            "auto_start": payload.auto_start,
            "source_type": "screenshot_guided_edit",
            "screenshot_count": len(payload.screenshots),
        },
    )
    await record_event(
        session,
        project_id=project.id,
        run_id=run.id,
        task_id=task.id,
        event_type="VISION_RUN_CREATED",
        actor_type="USER",
        actor_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        message="Vision-guided run created from screenshot + text intake.",
        payload={
            "goal_text": payload.goal_text,
            "page_url": payload.page_url,
            "source_type": "screenshot_guided_edit",
            "screenshot_count": len(payload.screenshots),
            "auto_deploy": payload.auto_deploy,
            "executor": executor_name,
            "auto_start": payload.auto_start,
        },
    )

    await session.commit()
    return VisionRunOut(
        task_id=task.id,
        run_id=run.id,
        status="queued" if payload.auto_start else "created",
        status_url=f"/projects/{project.id}/runs/{run.id}",
        source_type="screenshot_guided_edit",
    )


@router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    project_id: uuid.UUID,
    payload: RunCreate | None = None,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    executor_name = (payload.executor if payload else "codex").lower()
    architecture_summary = await summarize_architecture_profile(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
    )
    architecture_ready = bool(architecture_summary.profile_exists and architecture_summary.derived_ready)
    if executor_name != "dummy" and not architecture_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Architecture profile must be derived before starting a run. "
                "Open Project Overview -> Architecture Contract -> Manage, then run Bootstrap and Derive."
            ),
        )
    if project.workspace_id:
        await _check_workspace_token_limit(session, ctx, project.workspace_id)
    task_id = payload.task_id if payload else None
    request_key = str(payload.request_key).strip() if payload and payload.request_key else ""
    if request_key:
        existing = await _find_run_by_request_key(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            request_key=request_key,
        )
        if existing is not None:
            return _run_out(existing)
    try:
        run = await launch_run_for_project(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            executor_name=executor_name,
            task_id=task_id,
            actor_type="USER",
            run_kind=payload.run_kind if payload else None,
            schedule=True,
        )
        await record_event(
            session,
            project_id=project_id,
            run_id=run.id,
            event_type="RUN_ACTION_ACCEPTED",
            actor_type="USER",
            actor_id=getattr(ctx, "user_id", None),
            tenant_id=ctx.tenant_id,
            payload={"action": "start"},
        )
        if request_key:
            summary = dict(run.summary) if isinstance(run.summary, dict) else {}
            summary["request_key"] = request_key
            run.summary = summary
            session.add(run)
            await session.commit()
            await session.refresh(run)
        return _run_out(run)
    except ValueError as exc:
        detail = str(exc)
        if detail in {"Project not found", "Task not found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        if request_key:
            existing = await _find_run_by_request_key(
                session,
                tenant_id=ctx.tenant_id,
                project_id=project_id,
                request_key=request_key,
            )
            if existing is not None:
                return _run_out(existing)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


@router.get("/projects/{project_id}/stack-presets", response_model=List[StackPresetOut])
@public_router.get("/projects/{project_id}/stack-presets", response_model=List[StackPresetOut])
async def list_project_stack_presets(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[StackPresetOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    presets = await ensure_stack_presets(session, tenant_id=ctx.tenant_id, created_by=getattr(ctx, "user_id", None))
    await session.commit()
    return [StackPresetOut.model_validate(row) for row in presets]


@router.get("/projects/{project_id}/blueprint", response_model=ProjectBlueprintOut | None)
@public_router.get("/projects/{project_id}/blueprint", response_model=ProjectBlueprintOut | None)
async def fetch_project_blueprint(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectBlueprintOut | None:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    blueprint = await get_project_blueprint(session, tenant_id=ctx.tenant_id, project_id=project_id)
    if blueprint is None:
        return None
    return ProjectBlueprintOut.model_validate(blueprint)


@router.get("/projects/{project_id}/genesis-runs/latest", response_model=ProjectGenesisRunOut | None)
@public_router.get("/projects/{project_id}/genesis-runs/latest", response_model=ProjectGenesisRunOut | None)
async def fetch_latest_project_genesis_run(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectGenesisRunOut | None:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    genesis_run = await get_latest_genesis_run(session, tenant_id=ctx.tenant_id, project_id=project_id)
    if genesis_run is None:
        return None
    return ProjectGenesisRunOut.model_validate(genesis_run)


@router.post("/projects/{project_id}/blueprint", response_model=ProjectGenesisLaunchOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/projects/{project_id}/blueprint", response_model=ProjectGenesisLaunchOut, status_code=status.HTTP_201_CREATED)
async def create_project_blueprint(
    project_id: uuid.UUID,
    payload: ProjectBlueprintCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectGenesisLaunchOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        blueprint, snapshot, genesis_run = await run_project_genesis(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            blueprint_key=payload.blueprint_key,
            stack_preset_key=payload.stack_preset_key,
            deployment_profile=payload.deployment_profile,
            readiness_enforced=payload.readiness_enforced,
            created_by=payload.created_by or getattr(ctx, "user_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    latest_snapshot = await get_latest_topology_snapshot(session, tenant_id=ctx.tenant_id, project_id=project_id)
    return ProjectGenesisLaunchOut(
        blueprint=ProjectBlueprintOut.model_validate(blueprint),
        topology_snapshot=ProjectTopologySnapshotOut.model_validate(latest_snapshot or snapshot),
        genesis_run=ProjectGenesisRunOut.model_validate(genesis_run),
    )


@router.get("/projects/{project_id}/runs", response_model=List[RunOut])
@public_router.get("/projects/{project_id}/runs", response_model=List[RunOut])
async def list_runs(
    project_id: uuid.UUID,
    finalize_active: bool = Query(default=False),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[RunOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(Run)
        .where(Run.project_id == project_id, Run.tenant_id == ctx.tenant_id)
        .order_by(*_run_activity_ordering())
    )
    runs = result.scalars().all()
    if finalize_active:
        finalized_any = False
        for run in runs:
            if run.status in ACTIVE_RUN_STATUSES:
                prior = run.status
                await _maybe_finalize_run(session, run.id)
                if run.status != prior:
                    finalized_any = True
        if finalized_any:
            await session.commit()
            result = await session.execute(
                select(Run)
                .where(Run.project_id == project_id, Run.tenant_id == ctx.tenant_id)
                .order_by(*_run_activity_ordering())
            )
            runs = result.scalars().all()
    return [_run_out(r) for r in runs]


@router.get("/projects/{project_id}/runs/memory", response_model=RunMemoryResponse)
@public_router.get("/projects/{project_id}/runs/memory", response_model=RunMemoryResponse)
async def get_run_memory(
    project_id: uuid.UUID,
    goal: str | None = None,
    error: str | None = None,
    file: List[str] | None = Query(default=None),
    limit: int = 5,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunMemoryResponse:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return await find_similar_runs(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            goal_text=goal,
            error_text=error,
            files=file or [],
            limit=max(1, min(limit, 10)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/runs/{run_id}/strategies", response_model=RunStrategyGroupResponse, status_code=status.HTTP_201_CREATED)
@public_router.post("/runs/{run_id}/strategies", response_model=RunStrategyGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_run_strategies(
    run_id: uuid.UUID,
    payload: RunStrategyPlanRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunStrategyGroupResponse:
    try:
        return await create_strategy_group(
            session,
            tenant_id=ctx.tenant_id,
            source_run_id=run_id,
            request=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs/{run_id}/strategies", response_model=RunStrategyGroupResponse)
@public_router.get("/runs/{run_id}/strategies", response_model=RunStrategyGroupResponse)
async def get_run_strategies(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunStrategyGroupResponse:
    try:
        return await get_strategy_group(
            session,
            tenant_id=ctx.tenant_id,
            run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs/compare", response_model=RunComparisonResponse)
@public_router.get("/runs/compare", response_model=RunComparisonResponse)
async def compare_runs_endpoint(
    run_a: uuid.UUID,
    run_b: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunComparisonResponse:
    try:
        return await compare_runs(session, tenant_id=ctx.tenant_id, run_a_id=run_a, run_b_id=run_b)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=RunOut)
@public_router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)) -> RunOut:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _run_out(run)


@router.get("/runs/{run_id}/timeline", response_model=RunTimelineResponse)
@public_router.get("/runs/{run_id}/timeline", response_model=RunTimelineResponse)
async def get_run_timeline(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunTimelineResponse:
    try:
        return await build_run_timeline(session, tenant_id=ctx.tenant_id, run_id=run_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "Run not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


@router.get("/runs/{run_id}/narrative", response_model=RunNarrativeResponse)
@public_router.get("/runs/{run_id}/narrative", response_model=RunNarrativeResponse)
async def get_run_narrative(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunNarrativeResponse:
    try:
        return await build_run_narrative(session, tenant_id=ctx.tenant_id, run_id=run_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "Run not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


@router.post("/projects/{project_id}/connect-repo", response_model=ProjectRepositoryOut)
@public_router.post("/projects/{project_id}/connect-repo", response_model=ProjectRepositoryOut)
async def connect_project_repo(
    project_id: uuid.UUID,
    payload: ProjectRepositoryConnect,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectRepositoryOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        repo = await connect_repo(
            session,
            project=project,
            provider=payload.provider,
            repo_url=payload.repo_url,
            repo_full_name=payload.repo_full_name,
            default_branch=payload.default_branch,
            installation_id=payload.installation_id,
            auth_strategy=payload.auth_strategy,
            created_by=payload.created_by or ctx.user_id,
        )
        await log_activity(
            session,
            project_id=project.id,
            entity_type="project_repository",
            entity_id=repo.id,
            action_type="repo.connected",
            metadata={
                "provider": repo.provider,
                "repo_url": repo.repo_url,
                "default_branch": repo.default_branch,
                "auth_strategy": repo.auth_strategy,
            },
        )
        await bootstrap_architecture_profile(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project.id,
            refresh_repo_map_requested=False,
            created_by=payload.created_by or ctx.user_id,
        )
        await session.commit()
        await session.refresh(repo)
        return _project_repo_out(repo)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/projects/{project_id}/repo/preflight", response_model=ProjectRepositoryPreflightOut)
@public_router.post("/projects/{project_id}/repo/preflight", response_model=ProjectRepositoryPreflightOut)
async def preflight_project_repo(
    project_id: uuid.UUID,
    payload: ProjectRepositoryPreflightRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectRepositoryPreflightOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    repo = await get_project_repository(session, project_id=project_id, tenant_id=ctx.tenant_id)
    repo_url = (payload.repo_url or (repo.repo_url if repo else "")).strip()
    if not repo_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is required")

    try:
        result = preflight_repo_access(
            provider=payload.provider or (repo.provider if repo else "github"),
            repo_url=repo_url,
            repo_full_name=payload.repo_full_name if payload.repo_full_name is not None else (repo.repo_full_name if repo else None),
            default_branch=payload.default_branch or (repo.default_branch if repo else "main"),
            installation_id=payload.installation_id if payload.installation_id is not None else (repo.installation_id if repo else None),
            auth_strategy=payload.auth_strategy or (repo.auth_strategy if repo else "runtime_default"),
            clone=payload.clone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProjectRepositoryPreflightOut(**result.__dict__)


@router.get("/integrations/github/connect", response_model=GitHubConnectInfoOut)
@public_router.get("/integrations/github/connect", response_model=GitHubConnectInfoOut)
async def get_github_connect_info() -> GitHubConnectInfoOut:
    slug = (settings.github_app_slug or "").strip() or None
    enabled = bool(github_adapter and slug)
    install_url = f"https://github.com/apps/{slug}/installations/new" if enabled and slug else None
    return GitHubConnectInfoOut(
        enabled=enabled,
        app_slug=slug,
        allowed_org=settings.github_allowed_org,
        install_url=install_url,
        runtime_git_auth_mode=settings.runtime_git_auth_mode,
    )


@router.get(
    "/integrations/github/installations/{installation_id}/repositories",
    response_model=List[GitHubInstallationRepositoryOut],
)
@public_router.get(
    "/integrations/github/installations/{installation_id}/repositories",
    response_model=List[GitHubInstallationRepositoryOut],
)
async def list_github_installation_repositories(installation_id: int) -> List[GitHubInstallationRepositoryOut]:
    if github_adapter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GitHub App integration is not configured")
    try:
        repos = github_adapter.list_installation_repositories(installation_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load repositories for this GitHub installation",
        ) from exc
    return [GitHubInstallationRepositoryOut.model_validate(repo) for repo in repos]


@router.get("/projects/{project_id}/repo", response_model=ProjectRepositoryOut)
@public_router.get("/projects/{project_id}/repo", response_model=ProjectRepositoryOut)
async def get_project_repo(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectRepositoryOut:
    repo = await get_project_repository(session, project_id=project_id, tenant_id=ctx.tenant_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project repository not connected")
    return _project_repo_out(repo)


@router.get("/projects/{project_id}/foundation-readiness", response_model=FoundationReadinessOut)
@public_router.get("/projects/{project_id}/foundation-readiness", response_model=FoundationReadinessOut)
async def get_foundation_readiness(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> FoundationReadinessOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return FoundationReadinessOut(
        **await build_foundation_readiness(session, tenant_id=ctx.tenant_id, project_id=project_id)
    )


@router.get("/projects/{project_id}/environments", response_model=ProjectEnvironmentCenterOut)
@public_router.get("/projects/{project_id}/environments", response_model=ProjectEnvironmentCenterOut)
async def get_project_environment_center(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectEnvironmentCenterOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    var_rows = (
        await session.execute(
            select(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.tenant_id == ctx.tenant_id,
                ProjectEnvironmentVariable.project_id == project_id,
            )
        )
    ).scalars().all()
    validation_rows = (
        await session.execute(
            select(EnvironmentValidationResult).where(
                EnvironmentValidationResult.tenant_id == ctx.tenant_id,
                EnvironmentValidationResult.project_id == project_id,
            )
        )
    ).scalars().all()
    sync_rows = (
        await session.execute(
            select(EnvironmentSyncStatus).where(
                EnvironmentSyncStatus.tenant_id == ctx.tenant_id,
                EnvironmentSyncStatus.project_id == project_id,
            )
        )
    ).scalars().all()

    envs = ("PREVIEW", "STAGING", "PRODUCTION")
    profiles: list[ProjectEnvironmentProfileOut] = []
    for env in envs:
        env_vars = [row for row in var_rows if str(row.environment).upper() == env]
        configured = sum(1 for row in env_vars if (row.vault_ref and row.vault_ref.strip()) or (row.plain_value and row.plain_value.strip()))
        validations = [row for row in validation_rows if str(row.environment).upper() == env]
        validation_passed = sum(1 for row in validations if str(row.status).lower() == "pass")
        syncs = [row for row in sync_rows if str(row.environment).upper() == env]
        sync_healthy = sum(1 for row in syncs if str(row.status).lower() in {"healthy", "synced", "pass"} and not bool(row.drift_detected))
        profiles.append(
            ProjectEnvironmentProfileOut(
                environment=env,
                variables_configured=configured,
                variables_total=len(env_vars),
                validation_passed=validation_passed,
                validation_total=len(validations),
                sync_healthy=sync_healthy,
                sync_total=len(syncs),
            )
        )
    return ProjectEnvironmentCenterOut(project_id=project_id, workspace_id=project.workspace_id, environments=profiles)


@router.get("/projects/{project_id}/deployment-readiness", response_model=DeploymentReadinessContractOut)
@public_router.get("/projects/{project_id}/deployment-readiness", response_model=DeploymentReadinessContractOut)
async def get_project_deployment_readiness(
    project_id: uuid.UUID,
    environment: str | None = Query(default=None),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> DeploymentReadinessContractOut:
    try:
        payload = await compute_deployment_readiness(
            session=session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            environment=environment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DeploymentReadinessContractOut.model_validate(payload)


@router.get("/projects/{project_id}/environments/{environment}/variables", response_model=list[ProjectEnvironmentVariableOut])
@public_router.get("/projects/{project_id}/environments/{environment}/variables", response_model=list[ProjectEnvironmentVariableOut])
async def list_project_environment_variables(
    project_id: uuid.UUID,
    environment: str,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectEnvironmentVariableOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    env = environment.strip().upper()
    rows = (
        await session.execute(
            select(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.tenant_id == ctx.tenant_id,
                ProjectEnvironmentVariable.project_id == project_id,
                ProjectEnvironmentVariable.environment == env,
            ).order_by(ProjectEnvironmentVariable.var_key.asc())
        )
    ).scalars().all()
    return [_project_env_var_out(row) for row in rows]


@router.get("/projects/{project_id}/environment-templates", response_model=list[EnvironmentTemplateOut])
@public_router.get("/projects/{project_id}/environment-templates", response_model=list[EnvironmentTemplateOut])
async def list_project_environment_templates(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[EnvironmentTemplateOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    templates: list[EnvironmentTemplateOut] = []
    for key, data in ENVIRONMENT_TEMPLATES.items():
        templates.append(
            EnvironmentTemplateOut(
                key=key,
                name=data["name"],
                description=data["description"],
                deployment_targets=list(data.get("deployment_targets") or []),
                provider_mappings=dict(data.get("provider_mappings") or {}),
                variables=[EnvironmentTemplateVarOut(**row) for row in data.get("variables", [])],
            )
        )
    return templates


@router.post("/projects/{project_id}/environment-templates/{template_key}/apply", response_model=list[ProjectEnvironmentVariableOut])
@public_router.post("/projects/{project_id}/environment-templates/{template_key}/apply", response_model=list[ProjectEnvironmentVariableOut])
async def apply_project_environment_template(
    project_id: uuid.UUID,
    template_key: str,
    payload: EnvironmentTemplateApplyRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectEnvironmentVariableOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    normalized_key = template_key.strip().lower()
    template = ENVIRONMENT_TEMPLATES.get(normalized_key)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment template not found")
    env = (payload.environment or "").strip().upper()
    if env not in {"PREVIEW", "STAGING", "PRODUCTION"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="environment must be PREVIEW/STAGING/PRODUCTION")

    created_or_updated: list[ProjectEnvironmentVariable] = []
    for item in template.get("variables", []):
        if not payload.include_optional and not bool(item.get("required")):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        row = await session.scalar(
            select(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.tenant_id == ctx.tenant_id,
                ProjectEnvironmentVariable.project_id == project_id,
                ProjectEnvironmentVariable.environment == env,
                ProjectEnvironmentVariable.var_key == key,
            )
        )
        if row is None:
            row = ProjectEnvironmentVariable(
                tenant_id=ctx.tenant_id,
                workspace_id=project.workspace_id or ctx.workspace_id,
                project_id=project_id,
                environment=env,
                var_key=key,
            )
        row.value_kind = "secret"
        if not row.vault_ref:
            row.vault_ref = f"workspace/{project.workspace_id or ctx.workspace_id}/project/{project_id}/{env}/{key}".lower()
        row.required = bool(item.get("required"))
        row.source = "template"
        row.validation_regex = item.get("validation_regex")
        row.updated_by = ctx.user_id
        session.add(row)
        created_or_updated.append(row)

    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=project.workspace_id,
            action="project_env.template_apply",
            extra_metadata={
                "project_id": str(project_id),
                "environment": env,
                "template_key": normalized_key,
                "include_optional": bool(payload.include_optional),
                "variable_count": len(created_or_updated),
            },
        )
    )
    await session.commit()
    for row in created_or_updated:
        await session.refresh(row)
    return [_project_env_var_out(row) for row in created_or_updated]


@router.put("/projects/{project_id}/environments/{environment}/variables/{var_key}", response_model=ProjectEnvironmentVariableOut)
@public_router.put("/projects/{project_id}/environments/{environment}/variables/{var_key}", response_model=ProjectEnvironmentVariableOut)
async def upsert_project_environment_variable(
    project_id: uuid.UUID,
    environment: str,
    var_key: str,
    payload: ProjectEnvironmentVariableUpsertRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectEnvironmentVariableOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    env = environment.strip().upper()
    key = var_key.strip()
    if not env or not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="environment and var_key are required")
    value_kind = (payload.value_kind or "secret").strip().lower()
    if value_kind not in {"secret", "plain"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="value_kind must be 'secret' or 'plain'")
    if value_kind == "secret" and not ((payload.vault_ref or "").strip() or (payload.plain_value or "").strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="secret variables require vault_ref or plain_value")
    row = await session.scalar(
        select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.tenant_id == ctx.tenant_id,
            ProjectEnvironmentVariable.project_id == project_id,
            ProjectEnvironmentVariable.environment == env,
            ProjectEnvironmentVariable.var_key == key,
        )
    )
    if row is None:
        row = ProjectEnvironmentVariable(
            tenant_id=ctx.tenant_id,
            workspace_id=project.workspace_id or ctx.workspace_id,
            project_id=project_id,
            environment=env,
            var_key=key,
        )
    row.value_kind = value_kind
    inferred_vault_ref = f"workspace/{project.workspace_id or ctx.workspace_id}/project/{project_id}/{env}/{key}".lower()
    row.vault_ref = (payload.vault_ref or "").strip() or (inferred_vault_ref if value_kind == "secret" else None)
    if value_kind == "secret":
        if (payload.plain_value or "").strip():
            store_vault_secret(row.vault_ref or inferred_vault_ref, payload.plain_value or "")
        row.plain_value = None
    else:
        row.plain_value = payload.plain_value
    row.required = bool(payload.required)
    row.source = (payload.source or "").strip() or None
    row.validation_regex = (payload.validation_regex or "").strip() or None
    row.updated_by = ctx.user_id
    session.add(row)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=project.workspace_id,
            action="project_env_var.upsert",
            extra_metadata={
                "project_id": str(project_id),
                "environment": env,
                "var_key": key,
                "value_kind": value_kind,
                "has_vault_ref": bool(row.vault_ref),
                "has_plain_value": bool((row.plain_value or "").strip()),
            },
        )
    )
    await session.commit()
    await session.refresh(row)
    return _project_env_var_out(row)


@router.post("/projects/{project_id}/environments/{environment}/variables/{var_key}/secret", response_model=ProjectEnvironmentVariableOut)
@public_router.post("/projects/{project_id}/environments/{environment}/variables/{var_key}/secret", response_model=ProjectEnvironmentVariableOut)
async def write_project_environment_variable_secret(
    project_id: uuid.UUID,
    environment: str,
    var_key: str,
    payload: EnvironmentSecretWriteRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectEnvironmentVariableOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    env = environment.strip().upper()
    key = var_key.strip()
    row = await session.scalar(
        select(ProjectEnvironmentVariable).where(
            ProjectEnvironmentVariable.tenant_id == ctx.tenant_id,
            ProjectEnvironmentVariable.project_id == project_id,
            ProjectEnvironmentVariable.environment == env,
            ProjectEnvironmentVariable.var_key == key,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment variable not found")
    if row.value_kind != "secret":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secret write is only valid for secret variables")
    if not row.vault_ref:
        row.vault_ref = f"workspace/{project.workspace_id or ctx.workspace_id}/project/{project_id}/{env}/{key}".lower()
    store_vault_secret(row.vault_ref, payload.value)
    row.plain_value = None
    row.updated_by = ctx.user_id
    session.add(row)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=project.workspace_id,
            action="project_env_var.secret_write",
            extra_metadata={"project_id": str(project_id), "environment": env, "var_key": key, "vault_ref": row.vault_ref},
        )
    )
    await session.commit()
    await session.refresh(row)
    return _project_env_var_out(row)


@router.post("/projects/{project_id}/environments/{environment}/validate", response_model=list[EnvironmentValidationResultOut])
@public_router.post("/projects/{project_id}/environments/{environment}/validate", response_model=list[EnvironmentValidationResultOut])
async def validate_project_environment(
    project_id: uuid.UUID,
    environment: str,
    payload: EnvironmentValidateRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[EnvironmentValidationResultOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    env = environment.strip().upper()
    rows = (
        await session.execute(
            select(ProjectEnvironmentVariable).where(
                ProjectEnvironmentVariable.tenant_id == ctx.tenant_id,
                ProjectEnvironmentVariable.project_id == project_id,
                ProjectEnvironmentVariable.environment == env,
            )
        )
    ).scalars().all()
    check_keys = payload.checks or [row.var_key for row in rows if row.required]
    results: list[EnvironmentValidationResult] = []
    for check_key in check_keys:
        ref = str(check_key or "").strip()
        if not ref:
            continue
        matched = next((row for row in rows if row.var_key == ref), None)
        has_value = bool(matched and (((matched.vault_ref or "").strip()) or ((matched.plain_value or "").strip())))
        status_value = "pass" if has_value else "fail"
        result = EnvironmentValidationResult(
            tenant_id=ctx.tenant_id,
            workspace_id=project.workspace_id or ctx.workspace_id,
            project_id=project_id,
            environment=env,
            check_key=ref,
            status=status_value,
            message=None if has_value else "Missing value for required environment variable.",
            evidence={"value_kind": matched.value_kind if matched else None},
        )
        session.add(result)
        results.append(result)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=project.workspace_id,
            action="project_env.validate",
            reason=(payload.reason or "").strip() or None,
            extra_metadata={"project_id": str(project_id), "environment": env, "checks": check_keys},
        )
    )
    await session.commit()
    for result in results:
        await session.refresh(result)
    return [EnvironmentValidationResultOut.model_validate(result) for result in results]


@router.post("/projects/{project_id}/environments/{environment}/sync/{provider}", response_model=EnvironmentSyncStatusOut)
@public_router.post("/projects/{project_id}/environments/{environment}/sync/{provider}", response_model=EnvironmentSyncStatusOut)
async def sync_project_environment_to_provider(
    project_id: uuid.UUID,
    environment: str,
    provider: str,
    payload: EnvironmentSyncRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> EnvironmentSyncStatusOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    env = environment.strip().upper()
    normalized_provider = provider.strip().lower()
    if normalized_provider not in {"vercel", "render", "railway"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")
    connector = await session.scalar(
        select(DeploymentProviderConnector).where(
            DeploymentProviderConnector.tenant_id == ctx.tenant_id,
            DeploymentProviderConnector.provider == normalized_provider,
        )
    )
    token = resolve_vault_secret(connector.vault_ref) if connector and connector.vault_ref else None
    if connector is None:
        sync_status = "failed"
        sync_message = "No provider connector configured for this workspace/tenant."
    elif not token:
        sync_status = "failed"
        sync_message = "Provider connector secret could not be resolved from vault."
    else:
        sync_status = "synced"
        sync_message = "Sync accepted. Provider push will be orchestrated by deployment runtime."

    row = await session.scalar(
        select(EnvironmentSyncStatus).where(
            EnvironmentSyncStatus.tenant_id == ctx.tenant_id,
            EnvironmentSyncStatus.project_id == project_id,
            EnvironmentSyncStatus.environment == env,
            EnvironmentSyncStatus.provider == normalized_provider,
        )
    )
    if row is None:
        row = EnvironmentSyncStatus(
            tenant_id=ctx.tenant_id,
            workspace_id=project.workspace_id or ctx.workspace_id,
            project_id=project_id,
            environment=env,
            provider=normalized_provider,
        )
    row.status = sync_status
    row.message = sync_message
    row.drift_detected = sync_status != "synced"
    row.last_synced_at = datetime.now(timezone.utc)
    row.details = {
        "requested_by": ctx.user_id,
        "connector_id": str(connector.id) if connector else None,
        "connector_vault_ref_present": bool(connector and connector.vault_ref),
        "provider_token_resolved": bool(token),
    }
    session.add(row)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=project.workspace_id,
            action="project_env.sync",
            reason=(payload.reason or "").strip() or None,
            extra_metadata={"project_id": str(project_id), "environment": env, "provider": normalized_provider},
        )
    )
    await session.commit()
    await session.refresh(row)
    return EnvironmentSyncStatusOut.model_validate(row)


@router.get("/projects/{project_id}/environment-checklists", response_model=EnvironmentChecklistSummaryOut)
@public_router.get("/projects/{project_id}/environment-checklists", response_model=EnvironmentChecklistSummaryOut)
async def get_project_environment_checklists(
    project_id: uuid.UUID,
    reseed: bool = Query(default=True),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> EnvironmentChecklistSummaryOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return await _load_environment_checklists(session, ctx=ctx, project=project, reseed=reseed)


@router.get("/projects/{project_id}/governance-kpis", response_model=GovernanceKpisOut)
@public_router.get("/projects/{project_id}/governance-kpis", response_model=GovernanceKpisOut)
async def get_governance_kpis(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> GovernanceKpisOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    payload = await build_governance_kpis(session, tenant_id=ctx.tenant_id, project_id=project_id)
    return GovernanceKpisOut.model_validate(payload)


@router.get("/runs/{run_id}/impact-score", response_model=RunImpactScoreOut)
@public_router.get("/runs/{run_id}/impact-score", response_model=RunImpactScoreOut)
async def get_run_impact_score(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunImpactScoreOut:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    summary_row = await session.scalar(
        select(RunSummaryModel).where(RunSummaryModel.run_id == run.id, RunSummaryModel.tenant_id == ctx.tenant_id)
    )
    if summary_row is None:
        rows = await ensure_project_run_summaries(
            session,
            tenant_id=ctx.tenant_id,
            project_id=run.project_id,
            limit=20,
        )
        summary_row = next((item for item in rows if item.run_id == run.id), None)

    prediction = (run.summary or {}).get("impact_prediction") if isinstance(run.summary, dict) else None
    score = score_impact_prediction(
        prediction=prediction if isinstance(prediction, dict) else {},
        actual_files_changed=(summary_row.changed_files if summary_row else []),
        run_status=run.status,
        recovery_count=summary_row.recovery_count if summary_row else 0,
    )
    return RunImpactScoreOut(run_id=run.id, **score)


@router.post("/projects/{project_id}/preview-profile", response_model=ProjectPreviewProfileOut)
@public_router.post("/projects/{project_id}/preview-profile", response_model=ProjectPreviewProfileOut)
async def save_project_preview_profile(
    project_id: uuid.UUID,
    payload: ProjectPreviewProfileUpsert,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectPreviewProfileOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    profile = await upsert_project_preview_profile(
        session,
        project_id=project.id,
        tenant_id=ctx.tenant_id,
        payload=payload.model_dump(),
    )
    await log_activity(
        session,
        project_id=project.id,
        entity_type="project_preview_profile",
        entity_id=profile.id,
        action_type="preview_profile.saved",
        metadata={
            "mode": profile.mode,
            "enabled": profile.enabled,
            "frontend_root": profile.frontend_root,
            "backend_root": profile.backend_root,
            "ttl_hours": profile.ttl_hours,
        },
    )
    await bootstrap_architecture_profile(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project.id,
        refresh_repo_map_requested=False,
        created_by=ctx.user_id,
    )
    await session.commit()
    await session.refresh(profile)
    return _project_preview_profile_out(profile)


@router.get("/projects/{project_id}/preview-profile", response_model=ProjectPreviewProfileOut)
@public_router.get("/projects/{project_id}/preview-profile", response_model=ProjectPreviewProfileOut)
async def fetch_project_preview_profile(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectPreviewProfileOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    profile = await get_project_preview_profile(session, tenant_id=ctx.tenant_id, project_id=project_id)
    if profile is None:
        default_payload = ProjectPreviewProfileUpsert(
            frontend_start_command=DEFAULT_STATIC_START_COMMAND
        ).model_dump()
        profile = await upsert_project_preview_profile(
            session,
            project_id=project_id,
            tenant_id=ctx.tenant_id,
            payload=default_payload,
        )
        await session.commit()
        await session.refresh(profile)
    return _project_preview_profile_out(profile)


class RunStatusUpdate(BaseModel):
    status: str


class RunForkRequest(BaseModel):
    executor: str | None = None
    branch_name: str | None = None
    start_now: bool = True
    summary_overrides: dict = Field(default_factory=dict)
    request_key: str | None = None


class RunBudgetExtendRequest(BaseModel):
    additional_tokens: int = Field(default=0, ge=0)
    additional_cost_cents: float = Field(default=0.0, ge=0.0)
    auto_resume: bool = True
    reason: str | None = None


class RunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    task_id: uuid.UUID | None
    work_item_id: uuid.UUID | None
    event_type: str
    ts: datetime
    actor_type: str | None = None
    actor_id: str | None = None
    message: str | None = None
    payload: dict | None = None
    correlation_id: str | None = None


class ClaimRequest(BaseModel):
    limit: int = 1
    lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS


@router.patch("/runs/{run_id}/status", response_model=RunOut)
@public_router.patch("/runs/{run_id}/status", response_model=RunOut)
async def patch_run_status(
    run_id: uuid.UUID,
    payload: RunStatusUpdate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    target = payload.status.strip().upper()
    if target != "CANCELED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manual status updates are restricted; only CANCELED is allowed. Orchestrator controls other transitions.",
        )
    result = await session.execute(
        select(Run)
        .where(Run.id == run_id, Run.tenant_id == ctx.tenant_id, Run.status.notin_(["COMPLETED", "FAILED", "CANCELED"]))
        .with_for_update(skip_locked=True)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run already finished or locked.")
    prev = run.status
    ok = await guarded_update_run_status(session, run_id, ["QUEUED", "RUNNING"], "CANCELED")
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run already finished or locked.")
    await log_activity(
        session,
        project_id=run.project_id,
        entity_type="run",
        entity_id=run.id,
        action_type="run.status",
        metadata={"status": "CANCELED"},
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_CANCELED",
        actor_type="USER",
        payload={"previous": prev, "new": "CANCELED"},
    )
    await session.commit()
    await session.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/fork", response_model=RunOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/runs/{run_id}/fork", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def fork_existing_run(
    run_id: uuid.UUID,
    payload: RunForkRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    source_run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not source_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    request_key = str(payload.request_key or "").strip()
    if request_key:
        existing = await _find_run_by_request_key(
            session,
            tenant_id=ctx.tenant_id,
            project_id=source_run.project_id,
            request_key=request_key,
            source_run_id=source_run.id,
        )
        if existing is not None:
            return _run_out(existing)
    summary_overrides = dict(payload.summary_overrides or {})
    if request_key:
        summary_overrides["request_key"] = request_key
        summary_overrides["fork_source_run_id"] = str(source_run.id)
    forked = await fork_run(
        session,
        source_run=source_run,
        executor=payload.executor,
        branch_name=payload.branch_name,
        summary_overrides=summary_overrides,
        start_now=payload.start_now,
    )
    return _run_out(forked)


@router.post("/runs/{run_id}/resume", response_model=RunOut)
@public_router.post("/runs/{run_id}/resume", response_model=RunOut)
async def resume_existing_run(
    run_id: uuid.UUID,
    payload: RunResumeRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_ACTION_REQUESTED",
        actor_type="USER",
        actor_id=getattr(ctx, "user_id", None),
        tenant_id=ctx.tenant_id,
        payload={"action": "resume"},
    )
    try:
        await prepare_run_for_resume(
            session,
            run,
            actor_type="USER",
            actor_id=getattr(ctx, "user_id", None),
        )
        await session.commit()
        await session.refresh(run)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if payload.start_now:
        orchestrator = RunOrchestrator(SessionLocal, executor_name=run.executor)
        bind = session.get_bind()
        is_sqlite = bind is not None and bind.dialect.name == "sqlite"
        try:
            await orchestrator.bootstrap_in_session(
                session,
                run.id,
                actor_type="USER",
                actor_id=getattr(ctx, "user_id", None),
                executor_name=run.executor,
            )
            await session.commit()
            await session.refresh(run)
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if not is_sqlite:
            _schedule_orchestrator_start(
                orchestrator,
                run_id=run.id,
                actor_type="USER",
                actor_id=getattr(ctx, "user_id", None),
                executor_name=run.executor,
            )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_RESUMED",
        actor_type="USER",
        actor_id=getattr(ctx, "user_id", None),
        tenant_id=ctx.tenant_id,
        payload={"action": "resume", "start_now": bool(payload.start_now)},
    )

    return _run_out(run)


@router.post("/runs/{run_id}/budget/extend", response_model=RunOut)
@public_router.post("/runs/{run_id}/budget/extend", response_model=RunOut)
async def extend_run_budget(
    run_id: uuid.UUID,
    payload: RunBudgetExtendRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    if payload.additional_tokens <= 0 and payload.additional_cost_cents <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide a positive budget increase.")
    run = await session.scalar(
        _run_scoped(session, ctx, run_id).with_for_update(skip_locked=True)
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await sync_run_execution_contract_state(session, run)
    summary = dict(run.summary or {})
    contract = coerce_execution_contract(summary.get("execution_contract"))
    if contract is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run execution contract unavailable.")
    contract.budget.max_tokens = int(contract.budget.max_tokens) + int(payload.additional_tokens)
    contract.budget.max_cost_cents = round(float(contract.budget.max_cost_cents) + float(payload.additional_cost_cents), 4)
    contract.budget.refresh()
    summary["execution_contract"] = contract.to_dict()
    extensions = summary.get("budget_extensions") if isinstance(summary.get("budget_extensions"), list) else []
    extensions.append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "additional_tokens": int(payload.additional_tokens),
            "additional_cost_cents": float(payload.additional_cost_cents),
            "reason": (payload.reason or "").strip() or None,
            "actor_id": ctx.user_id,
        }
    )
    summary["budget_extensions"] = extensions[-20:]
    summary.pop("budget_pause", None)
    if run.status == "PAUSED" and payload.auto_resume:
        run.status = "QUEUED"
        run.finished_at = None
        failed_items = (
            await session.execute(
                select(WorkItem).where(WorkItem.run_id == run.id, WorkItem.status == "FAILED")
            )
        ).scalars().all()
        for item in failed_items:
            result = item.result if isinstance(item.result, dict) else {}
            message = str(result.get("message") or "").lower()
            failure_class = str(result.get("failure_class") or "").lower()
            if "run_budget_exhausted" in message or "budget_exhausted" in failure_class:
                item.status = "QUEUED"
                item.attempt = max(0, int(item.attempt))
                item.assigned_agent_id = None
                item.lease_expires_at = None
                item.started_at = None
                item.finished_at = None
                item.last_error = None
                item.result = {}
                session.add(item)
    run.summary = summary
    session.add(run)
    await log_activity(
        session,
        project_id=run.project_id,
        entity_type="run",
        entity_id=run.id,
        action_type="run.budget.extend",
        metadata={
            "additional_tokens": int(payload.additional_tokens),
            "additional_cost_cents": float(payload.additional_cost_cents),
            "auto_resume": bool(payload.auto_resume),
            "reason": (payload.reason or "").strip() or None,
        },
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_BUDGET_EXTENDED",
        actor_type="USER",
        actor_id=ctx.user_id,
        payload={
            "additional_tokens": int(payload.additional_tokens),
            "additional_cost_cents": float(payload.additional_cost_cents),
            "auto_resume": bool(payload.auto_resume),
            "new_max_tokens": contract.budget.max_tokens,
            "new_max_cost_cents": contract.budget.max_cost_cents,
        },
    )
    if run.status == "QUEUED" and payload.auto_resume:
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_BUDGET_RESUMED",
            actor_type="USER",
            actor_id=ctx.user_id,
            payload={"previous": "PAUSED", "new": "QUEUED"},
        )
    await session.commit()
    await session.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/retry-push", response_model=RunOut)
@public_router.post("/runs/{run_id}/retry-push", response_model=RunOut)
async def retry_run_branch_push(
    run_id: uuid.UUID,
    payload: RunRetryPushRequest | None = None,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in {"COMPLETED", "FAILED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run must be completed before retrying push")
    if run.workspace_status != "SEEDED" or not run.repo_path:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run workspace is not ready for push retry")

    try:
        result = await publish_run_branch_if_ready(
            session,
            run=run,
            actor_type="USER",
            actor_id=getattr(ctx, "user_id", None),
            auth_strategy_override=payload.auth_strategy if payload else None,
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run is not eligible for branch push")
    except HTTPException:
        raise
    except Exception as exc:
        summary = dict(run.summary or {})
        summary["remote_branch_push_error"] = str(exc)
        summary["remote_branch_pushed"] = False
        summary["delivery_manual_push_required"] = True
        run.summary = summary
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_BRANCH_PUSH_FAILED",
            actor_type="USER",
            actor_id=getattr(ctx, "user_id", None),
            tenant_id=run.tenant_id,
            message=str(exc),
            payload={
                "branch_name": run.branch_name,
                "workspace_status": run.workspace_status,
                "manual_push_required": True,
            },
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Branch push retry failed: {exc}") from exc

    summary = dict(run.summary or {})
    summary["delivery_manual_push_required"] = False
    run.summary = summary
    if run.status == "FAILED":
        run.status = "COMPLETED"
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/unblock", response_model=RunUnblockResponse)
@public_router.post("/runs/{run_id}/unblock", response_model=RunUnblockResponse)
async def unblock_run(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunUnblockResponse:
    from app.runtime.leases import reclaim_expired_work_items, reclaim_orphaned_work_items

    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in {"RUNNING", "QUEUED"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is {run.status}; unblock is only allowed for RUNNING/QUEUED runs.",
        )

    await reclaim_expired_work_items(session, run_id=run.id)
    await reclaim_orphaned_work_items(session, run_id=run.id)

    counts_before = (
        await session.execute(
            select(
                func.count().filter(WorkItem.status == "QUEUED"),
                func.count().filter(WorkItem.status.in_(["RUNNING", "CLAIMED"])),
            ).where(WorkItem.run_id == run.id)
        )
    ).first()
    queued_before, active_before = counts_before
    runnable_before_items = await _runnable_queued_items_for_run(session, run.id)
    runnable_before = len(runnable_before_items)

    nudged_agent_ids: list[str] = []
    if runnable_before > 0:
        from app.runtime.worker_service import tick_worker

        agents = (
            await session.execute(
                select(Agent)
                .where(Agent.status == "ACTIVE")
                .order_by(Agent.last_heartbeat_at.desc(), Agent.created_at.desc())
                .limit(3)
            )
        ).scalars().all()
        await session.commit()
        for agent in agents:
            await tick_worker(agent.id)
            nudged_agent_ids.append(str(agent.id))

    counts_after = (
        await session.execute(
            select(
                func.count().filter(WorkItem.status == "QUEUED"),
                func.count().filter(WorkItem.status.in_(["RUNNING", "CLAIMED"])),
            ).where(WorkItem.run_id == run.id)
        )
    ).first()
    queued_after, active_after = counts_after
    runnable_after = len(await _runnable_queued_items_for_run(session, run.id))
    refreshed_run = await session.get(Run, run.id)

    return RunUnblockResponse(
        run_id=run.id,
        run_status=refreshed_run.status if refreshed_run else run.status,
        nudged=bool(nudged_agent_ids),
        nudged_agent_ids=nudged_agent_ids,
        queued_before=queued_before or 0,
        runnable_before=runnable_before,
        active_before=active_before or 0,
        queued_after=queued_after or 0,
        runnable_after=runnable_after,
        active_after=active_after or 0,
        detail="No runnable queued items found." if runnable_before == 0 else "Worker nudge triggered.",
    )


@router.post("/runs/{run_id}/discard", response_model=RunDiscardResponse)
@public_router.post("/runs/{run_id}/discard", response_model=RunDiscardResponse)
async def discard_run_workspace(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunDiscardResponse:
    run = await session.scalar(
        _run_scoped(session, ctx, run_id).with_for_update(skip_locked=True)
    )
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    previous_status = run.status
    if run.status in {"QUEUED", "RUNNING"}:
        ok = await guarded_update_run_status(session, run.id, ["QUEUED", "RUNNING"], "CANCELED")
        if ok:
            run.status = "CANCELED"
            run.finished_at = run.finished_at or datetime.now(timezone.utc)
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_CANCELED",
                actor_type="USER",
                actor_id=ctx.user_id,
                payload={"previous": previous_status, "new": "CANCELED", "reason": "discard_requested"},
            )

    preview = await stop_run_preview(session, tenant_id=ctx.tenant_id, run_id=run.id)
    workspace_root = run.workspace_root
    try:
        workspace_deleted = destroy_run_workspace(run)
    except ValueError as exc:
        detail = str(exc)
        conflict_markers = ("already exists", "conflict", "422")
        code = status.HTTP_409_CONFLICT if any(marker in detail.lower() for marker in conflict_markers) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc

    run.workspace_root = None
    run.repo_path = None
    run.workspace_status = "PENDING"
    run.workspace_error = None
    summary = dict(run.summary or {})
    summary["workspace_discarded"] = True
    summary["workspace_discarded_at"] = datetime.now(timezone.utc).isoformat()
    summary["workspace_discarded_by"] = ctx.user_id or "ui-user"
    run.summary = summary
    session.add(run)

    await log_activity(
        session,
        project_id=run.project_id,
        entity_type="run",
        entity_id=run.id,
        action_type="run.discard",
        metadata={
            "previous_status": previous_status,
            "status": run.status,
            "workspace_deleted": workspace_deleted,
            "workspace_root": workspace_root,
            "preview_status": preview.status,
        },
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_DISCARDED",
        actor_type="USER",
        actor_id=ctx.user_id,
        payload={
            "workspace_deleted": workspace_deleted,
            "workspace_root": workspace_root,
            "preview_status": preview.status,
        },
    )
    await session.commit()
    await session.refresh(run)

    return RunDiscardResponse(
        run_id=run.id,
        run_status=run.status,
        preview_status=preview.status,
        workspace_deleted=workspace_deleted,
        workspace_root=workspace_root,
        detail="Run workspace discarded and preview stopped.",
    )


@router.post("/runs/{run_id}/create-pr", response_model=PullRequestOut)
@public_router.post("/runs/{run_id}/create-pr", response_model=PullRequestOut)
async def create_run_pull_request(
    run_id: uuid.UUID,
    payload: PullRequestCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> PullRequestOut:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_ACTION_REQUESTED",
        actor_type="USER",
        actor_id=getattr(ctx, "user_id", None),
        tenant_id=ctx.tenant_id,
        payload={"action": "create_pr"},
    )
    # Idempotency guard: if this run already has a created PR for the requested/current branch,
    # return that PR payload instead of attempting a duplicate create.
    existing_summary = run.summary or {}
    existing_pr_url = str(existing_summary.get("pull_request_url") or "").strip()
    existing_branch = str(existing_summary.get("pull_request_branch") or run.branch_name or "").strip()
    requested_branch = str(payload.branch_name or "").strip()
    if existing_pr_url and (not requested_branch or requested_branch == existing_branch):
        existing_pr_artifact = await session.scalar(
            select(Artifact)
            .where(
                Artifact.run_id == run.id,
                Artifact.tenant_id == run.tenant_id,
                Artifact.project_id == run.project_id,
                Artifact.type == "pull_request",
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        if existing_pr_artifact is not None:
            metadata = existing_pr_artifact.extra_metadata or {}
            return PullRequestOut(
                run_id=run.id,
                artifact_id=existing_pr_artifact.id,
                pull_request_url=existing_pr_url,
                pull_request_number=existing_summary.get("pull_request_number") or metadata.get("number"),
                branch_name=existing_branch or str(metadata.get("head") or requested_branch or ""),
                base_branch=str(metadata.get("base") or "main"),
                commit_sha=str(
                    existing_summary.get("pull_request_commit_sha")
                    or metadata.get("commit_sha")
                    or ""
                ),
            )
    artifact = None
    if payload.artifact_id:
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.id == payload.artifact_id,
                Artifact.project_id == run.project_id,
                Artifact.tenant_id == ctx.tenant_id,
            )
        )
        if artifact is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    try:
        result = await create_pr_from_artifact(
            session,
            run=run,
            artifact=artifact,
            title=payload.title,
            body=payload.body,
            branch_name=payload.branch_name,
        )
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_ACTION_ACCEPTED",
            actor_type="USER",
            actor_id=getattr(ctx, "user_id", None),
            tenant_id=ctx.tenant_id,
            payload={"action": "create_pr"},
        )
        return PullRequestOut.model_validate(result)
    except ValueError as exc:
        detail = str(exc)
        conflict_markers = ("already exists", "conflict", "422")
        code = status.HTTP_409_CONFLICT if any(marker in detail.lower() for marker in conflict_markers) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/runs/{run_id}/preview", response_model=RunPreviewOut)
@public_router.post("/runs/{run_id}/preview", response_model=RunPreviewOut)
async def create_run_preview(
    run_id: uuid.UUID,
    payload: RunPreviewLaunchRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunPreviewOut:
    try:
        preview = await launch_run_preview(
            session,
            tenant_id=ctx.tenant_id,
            run_id=run_id,
            reuse_if_healthy=payload.reuse_if_healthy,
        )
        await log_activity(
            session,
            project_id=preview.project_id,
            entity_type="run_preview",
            entity_id=run_id,
            action_type="preview.launched",
            metadata={
                "status": preview.status,
                "preview_url": preview.preview_url,
                "mode": preview.mode,
                "expires_at": preview.expires_at.isoformat() if preview.expires_at else None,
            },
        )
        await session.commit()
        return preview
    except ValueError as exc:
        detail = str(exc)
        code = status.HTTP_400_BAD_REQUEST
        if detail == "Run not found":
            code = status.HTTP_404_NOT_FOUND
        elif detail in {
            "Project preview profile is not configured",
            "Run must be completed before preview launch",
            "Project preview limit reached",
            "Global preview limit reached",
            "Compose-only preview profiles are not supported in the local preview launcher yet",
        }:
            code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=detail) from exc


@router.get("/runs/{run_id}/preview", response_model=RunPreviewOut)
@public_router.get("/runs/{run_id}/preview", response_model=RunPreviewOut)
async def fetch_run_preview(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunPreviewOut:
    try:
        return await get_run_preview(session, tenant_id=ctx.tenant_id, run_id=run_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "Run not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


@router.delete("/runs/{run_id}/preview", response_model=RunPreviewOut)
@public_router.delete("/runs/{run_id}/preview", response_model=RunPreviewOut)
async def delete_run_preview(
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RunPreviewOut:
    try:
        preview = await stop_run_preview(session, tenant_id=ctx.tenant_id, run_id=run_id)
        await log_activity(
            session,
            project_id=preview.project_id,
            entity_type="run_preview",
            entity_id=run_id,
            action_type="preview.stopped",
            metadata={
                "status": preview.status,
                "preview_url": preview.preview_url,
            },
        )
        await session.commit()
        return preview
    except ValueError as exc:
        detail = str(exc)
        if detail == "Run not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


def _provider_bootstrap_links(provider: str, repository_url: str | None, project_name: str) -> tuple[str | None, str | None]:
    normalized = provider.strip().lower()
    if normalized == "vercel":
        if repository_url:
            link = f"https://vercel.com/new/clone?repository-url={quote_plus(repository_url)}"
            return link, "https://vercel.com/dashboard"
        return "https://vercel.com/new", "https://vercel.com/dashboard"
    if normalized == "render":
        return "https://dashboard.render.com/select-repo", "https://dashboard.render.com"
    if normalized == "railway":
        return "https://railway.com/new", "https://railway.com/project"
    if normalized == "fly":
        return "https://fly.io/dashboard", "https://fly.io/dashboard"
    slug = quote_plus(project_name.strip().lower().replace(" ", "-"))
    return f"https://{normalized}.com/new?project={slug}", None


async def _enforce_deployment_readiness_contract(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    environment: str,
) -> None:
    readiness = await compute_deployment_readiness(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        environment=environment,
    )
    env = str(readiness.get("environment") or environment).upper()
    safe_to_preview = bool(readiness.get("safe_to_preview"))
    safe_to_production = bool(readiness.get("safe_to_production"))
    blockers = [str(item) for item in (readiness.get("blockers") or []) if str(item).strip()]
    if env == "PRODUCTION" and not safe_to_production:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DEPLOYMENT_POLICY_BLOCKED",
                "message": "Production deployment blocked by readiness policy",
                "blockers": blockers[:8],
                "allowed_actions": [
                    "open_environment_center",
                    "validate_environment",
                    "sync_environment",
                    "deploy_preview" if safe_to_preview else "fix_readiness_blockers",
                ],
            },
        )
    if env != "PRODUCTION" and not safe_to_preview:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DEPLOYMENT_POLICY_BLOCKED",
                "message": "Preview/staging deployment blocked by readiness policy",
                "blockers": blockers[:8],
                "allowed_actions": [
                    "open_environment_center",
                    "validate_environment",
                    "sync_environment",
                    "fix_readiness_blockers",
                ],
            },
        )


async def _enforce_rollback_safety_policy(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    source: ProjectDeployment,
) -> None:
    blockers: list[str] = []
    rollback_target = await session.scalar(
        select(ProjectDeployment)
        .where(
            ProjectDeployment.tenant_id == tenant_id,
            ProjectDeployment.project_id == source.project_id,
            ProjectDeployment.provider == source.provider,
            ProjectDeployment.environment == source.environment,
            ProjectDeployment.id != source.id,
            ProjectDeployment.status == "READY",
            ProjectDeployment.created_at <= source.created_at,
        )
        .order_by(ProjectDeployment.created_at.desc(), ProjectDeployment.id.desc())
    )
    if rollback_target is None:
        blockers.append("No previous healthy deployment found for rollback target")
    elif not (rollback_target.deployment_url or "").strip():
        blockers.append("Rollback target has no deployment URL")

    connector = await session.scalar(
        select(DeploymentProviderConnector).where(
            DeploymentProviderConnector.tenant_id == tenant_id,
            DeploymentProviderConnector.provider == source.provider,
        )
    )
    if connector is None:
        blockers.append(f"{source.provider} connector missing")
    elif not (connector.vault_ref or "").strip() or not resolve_vault_secret(connector.vault_ref):
        blockers.append(f"{source.provider} connector secret invalid or unavailable")

    if blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DEPLOYMENT_POLICY_BLOCKED",
                "message": "Rollback blocked by safety policy",
                "blockers": blockers,
                "allowed_actions": [
                    "open_deployment_governance",
                    "configure_provider_connector",
                    "inspect_deployment_history",
                ],
            },
        )


@router.post("/projects/{project_id}/deployments", response_model=ProjectDeploymentOut)
@public_router.post("/projects/{project_id}/deployments", response_model=ProjectDeploymentOut)
async def create_project_deployment(
    project_id: uuid.UUID,
    payload: ProjectDeploymentCreateRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectDeploymentOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.workspace_id:
        await _check_workspace_deployment_limit(session, ctx, project.workspace_id)

    request_key = (payload.request_key or "").strip() or None
    if request_key:
        existing = await session.scalar(
            select(ProjectDeployment).where(
                ProjectDeployment.tenant_id == ctx.tenant_id,
                ProjectDeployment.project_id == project_id,
                ProjectDeployment.request_key == request_key,
            )
        )
        if existing is not None:
            return ProjectDeploymentOut.model_validate(existing)

    run_id = payload.run_id
    run: Run | None = None
    if run_id:
        run = await session.scalar(
            select(Run).where(
                Run.id == run_id,
                Run.project_id == project_id,
                Run.tenant_id == ctx.tenant_id,
            )
        )
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    environment = (payload.environment or "PREVIEW").strip().upper()
    if environment not in {"PREVIEW", "STAGING", "PRODUCTION"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="environment must be PREVIEW, STAGING, or PRODUCTION")
    await _enforce_deployment_readiness_contract(
        session=session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        environment=environment,
    )
    provider = (payload.provider or "vercel").strip().lower()
    deployment_strategy = (payload.deployment_strategy or "static_frontend").strip().lower()
    target = (payload.target or "user_app").strip().lower()
    repo = (payload.repository_url or "").strip() or None
    repo_full_name = (payload.repository_full_name or "").strip() or None
    branch_name = (payload.branch_name or run.branch_name if run else None)
    profile = await session.scalar(
        select(DeploymentProfile).where(
            DeploymentProfile.tenant_id == ctx.tenant_id,
            DeploymentProfile.project_id == project_id,
            DeploymentProfile.environment == environment,
        )
    )
    if profile is not None:
        provider = profile.provider or provider
        deployment_strategy = profile.deployment_strategy or deployment_strategy

    deployment_url, dashboard_url = _provider_bootstrap_links(provider, repo, project.name)
    requested_by = (payload.created_by or ctx.user_id or "ui-user").strip()
    profile_env_schema = profile.env_schema if profile and isinstance(profile.env_schema, dict) else {}
    connector: DeploymentProviderConnector | None = None
    if profile and profile.provider_connector_id:
        connector = await session.scalar(
            select(DeploymentProviderConnector).where(
                DeploymentProviderConnector.id == profile.provider_connector_id,
                DeploymentProviderConnector.tenant_id == ctx.tenant_id,
            )
        )
    integration_mode = (payload.integration_mode or str(profile_env_schema.get("integration_mode") or "bootstrap_link")).strip().lower()
    bootstrap_message = (
        "Provider API managed deployment configured."
        if integration_mode == "managed_api"
        else "Provider API handoff pending. Open deployment_url to complete one-click import."
    )
    deployment = ProjectDeployment(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        run_id=run_id,
        provider=provider,
        environment=environment,
        deployment_strategy=deployment_strategy,
        target=target,
        status="QUEUED",
        request_key=request_key,
        deployment_url=deployment_url,
        dashboard_url=dashboard_url,
        created_by=requested_by,
        extra_metadata={
            "repository_url": repo,
            "repository_full_name": repo_full_name,
            "branch_name": branch_name,
            "env_keys": sorted((payload.env_overrides or {}).keys()),
            "integration_mode": integration_mode,
            "environment": environment,
            "deployment_strategy": deployment_strategy,
            "healthcheck_path": profile.healthcheck_path if profile else "/",
            "vercel_deploy_hook_url": profile_env_schema.get("vercel_deploy_hook_url"),
            "render_deploy_hook_url": profile_env_schema.get("render_deploy_hook_url"),
            "provider_connector_id": str(connector.id) if connector else None,
            "provider_connector_vault_ref": connector.vault_ref if connector else None,
            "message": bootstrap_message,
        },
    )
    session.add(deployment)
    await log_activity(
        session,
        project_id=project_id,
        entity_type="project_deployment",
        entity_id=deployment.id,
        action_type="deployment.queued",
        metadata={
            "provider": provider,
            "target": target,
            "run_id": str(run_id) if run_id else None,
            "request_key": request_key,
        },
    )
    await session.commit()
    await session.refresh(deployment)
    return ProjectDeploymentOut.model_validate(deployment)


@router.get("/projects/{project_id}/deployments", response_model=List[ProjectDeploymentOut])
@public_router.get("/projects/{project_id}/deployments", response_model=List[ProjectDeploymentOut])
async def list_project_deployments(
    project_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[ProjectDeploymentOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(ProjectDeployment)
        .where(ProjectDeployment.tenant_id == ctx.tenant_id, ProjectDeployment.project_id == project_id)
        .order_by(ProjectDeployment.created_at.desc(), ProjectDeployment.id.desc())
        .limit(limit)
    )
    return [ProjectDeploymentOut.model_validate(item) for item in result.scalars().all()]


@router.get("/deployments/{deployment_id}", response_model=ProjectDeploymentOut)
@public_router.get("/deployments/{deployment_id}", response_model=ProjectDeploymentOut)
async def get_project_deployment(
    deployment_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectDeploymentOut:
    deployment = await session.scalar(
        select(ProjectDeployment).where(
            ProjectDeployment.id == deployment_id,
            ProjectDeployment.tenant_id == ctx.tenant_id,
        )
    )
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    return ProjectDeploymentOut.model_validate(deployment)


@router.post("/deployments/{deployment_id}/retry", response_model=ProjectDeploymentOut)
@public_router.post("/deployments/{deployment_id}/retry", response_model=ProjectDeploymentOut)
async def retry_project_deployment(
    deployment_id: uuid.UUID,
    payload: ProjectDeploymentRetryRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectDeploymentOut:
    deployment = await session.scalar(
        select(ProjectDeployment).where(
            ProjectDeployment.id == deployment_id,
            ProjectDeployment.tenant_id == ctx.tenant_id,
        )
    )
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    retryable = {"FAILED_VALIDATION", "FAILED_BUILD", "FAILED_DEPLOY", "FAILED_HEALTH_CHECK", "MANUAL_ACTION_REQUIRED"}
    if deployment.status not in retryable and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Deployment in status {deployment.status} is not retryable without force.",
        )
    await _enforce_deployment_readiness_contract(
        session=session,
        tenant_id=ctx.tenant_id,
        project_id=deployment.project_id,
        environment=deployment.environment,
    )
    previous_status = deployment.status
    deployment.status = "QUEUED"
    deployment.error_message = None
    metadata = dict(deployment.extra_metadata or {})
    metadata["last_retry_at"] = datetime.now(timezone.utc).isoformat()
    deployment.extra_metadata = metadata
    await log_activity(
        session,
        project_id=deployment.project_id,
        entity_type="project_deployment",
        entity_id=deployment.id,
        action_type="deployment.retried",
        metadata={
            "previous_status": previous_status,
            "force": payload.force,
        },
    )
    await session.commit()
    await session.refresh(deployment)
    return ProjectDeploymentOut.model_validate(deployment)


@router.get("/deployments/{deployment_id}/events", response_model=List[DeploymentEventOut])
@public_router.get("/deployments/{deployment_id}/events", response_model=List[DeploymentEventOut])
async def list_project_deployment_events(
    deployment_id: uuid.UUID,
    limit: int = Query(default=60, ge=1, le=300),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[DeploymentEventOut]:
    deployment = await session.scalar(
        select(ProjectDeployment).where(
            ProjectDeployment.id == deployment_id,
            ProjectDeployment.tenant_id == ctx.tenant_id,
        )
    )
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    result = await session.execute(
        select(ActivityLog)
        .where(
            ActivityLog.tenant_id == ctx.tenant_id,
            ActivityLog.project_id == deployment.project_id,
            ActivityLog.entity_type == "project_deployment",
            ActivityLog.entity_id == deployment.id,
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        DeploymentEventOut(
            id=row.id,
            created_at=row.created_at,
            action_type=row.action_type,
            event_type=row.event_type,
            actor=row.actor,
            extra_metadata=row.extra_metadata,
        )
        for row in rows
    ]


@router.post("/deployments/{deployment_id}/rollback", response_model=ProjectDeploymentOut)
@public_router.post("/deployments/{deployment_id}/rollback", response_model=ProjectDeploymentOut)
async def rollback_project_deployment(
    deployment_id: uuid.UUID,
    payload: ProjectDeploymentRollbackRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectDeploymentOut:
    source = await session.scalar(
        select(ProjectDeployment).where(
            ProjectDeployment.id == deployment_id,
            ProjectDeployment.tenant_id == ctx.tenant_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    if source.status != "READY":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only READY deployments can be rolled back")
    await _enforce_rollback_safety_policy(
        session=session,
        tenant_id=ctx.tenant_id,
        source=source,
    )
    request_key = (payload.request_key or "").strip() or None
    if request_key:
        existing = await session.scalar(
            select(ProjectDeployment).where(
                ProjectDeployment.tenant_id == ctx.tenant_id,
                ProjectDeployment.project_id == source.project_id,
                ProjectDeployment.request_key == request_key,
            )
        )
        if existing is not None:
            return ProjectDeploymentOut.model_validate(existing)
    rollback = ProjectDeployment(
        tenant_id=source.tenant_id,
        project_id=source.project_id,
        run_id=source.run_id,
        provider=source.provider,
        environment=source.environment,
        deployment_strategy=source.deployment_strategy,
        target=source.target,
        status="ROLLBACK_PENDING",
        request_key=request_key,
        rollback_source_deployment_id=source.id,
        rollback_reason=(payload.reason or "").strip() or "manual rollback",
        rollback_trigger=(payload.trigger or "manual").strip().lower(),
        created_by=(payload.created_by or ctx.user_id or "ui-user"),
        extra_metadata={
            "integration_mode": "managed_api",
            "provider_connector_id": (source.extra_metadata or {}).get("provider_connector_id"),
            "provider_connector_vault_ref": (source.extra_metadata or {}).get("provider_connector_vault_ref"),
            "repository_url": (source.extra_metadata or {}).get("repository_url"),
            "repository_full_name": (source.extra_metadata or {}).get("repository_full_name"),
            "branch_name": (source.extra_metadata or {}).get("branch_name"),
            "render_service_id": (source.extra_metadata or {}).get("render_service_id"),
            "rollback_of_deployment_id": str(source.id),
        },
    )
    session.add(rollback)
    await log_activity(
        session,
        project_id=source.project_id,
        entity_type="project_deployment",
        entity_id=rollback.id,
        action_type="deployment.rollback_requested",
        event_type="ROLLBACK_PENDING",
        actor=ctx.user_id,
        metadata={
            "source_deployment_id": str(source.id),
            "reason": rollback.rollback_reason,
            "trigger": rollback.rollback_trigger,
        },
    )
    await session.commit()
    await session.refresh(rollback)
    return ProjectDeploymentOut.model_validate(rollback)


@router.post("/deployments/{deployment_id}/promote", response_model=ProjectDeploymentOut)
@public_router.post("/deployments/{deployment_id}/promote", response_model=ProjectDeploymentOut)
async def promote_project_deployment(
    deployment_id: uuid.UUID,
    payload: ProjectDeploymentPromoteRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectDeploymentOut:
    source = await session.scalar(
        select(ProjectDeployment).where(
            ProjectDeployment.id == deployment_id,
            ProjectDeployment.tenant_id == ctx.tenant_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    if source.status != "READY":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only READY deployments can be promoted")
    target_environment = (payload.target_environment or "").strip().upper()
    if target_environment not in {"STAGING", "PRODUCTION"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_environment must be STAGING or PRODUCTION")
    await _enforce_deployment_readiness_contract(
        session=session,
        tenant_id=ctx.tenant_id,
        project_id=source.project_id,
        environment=target_environment,
    )
    request_key = (payload.request_key or "").strip() or None
    if request_key:
        existing = await session.scalar(
            select(ProjectDeployment).where(
                ProjectDeployment.tenant_id == ctx.tenant_id,
                ProjectDeployment.project_id == source.project_id,
                ProjectDeployment.request_key == request_key,
            )
        )
        if existing is not None:
            return ProjectDeploymentOut.model_validate(existing)
    promoted = ProjectDeployment(
        tenant_id=source.tenant_id,
        project_id=source.project_id,
        run_id=source.run_id,
        provider=source.provider,
        environment=target_environment,
        promoted_from_environment=source.environment,
        deployment_strategy=source.deployment_strategy,
        target=source.target,
        status="QUEUED",
        request_key=request_key,
        created_by=(payload.created_by or ctx.user_id or "ui-user"),
        extra_metadata={
            **dict(source.extra_metadata or {}),
            "integration_mode": "managed_api",
            "promotion_source_deployment_id": str(source.id),
            "promotion_reason": (payload.reason or "").strip() or None,
        },
    )
    session.add(promoted)
    await log_activity(
        session,
        project_id=source.project_id,
        entity_type="project_deployment",
        entity_id=promoted.id,
        action_type="deployment.promoted",
        event_type="PROMOTION_QUEUED",
        actor=ctx.user_id,
        metadata={
            "source_deployment_id": str(source.id),
            "from_environment": source.environment,
            "to_environment": target_environment,
        },
    )
    await session.commit()
    await session.refresh(promoted)
    return ProjectDeploymentOut.model_validate(promoted)


@router.post("/projects/{project_id}/deployments/preflight")
@public_router.post("/projects/{project_id}/deployments/preflight")
async def preflight_project_deployment(
    project_id: uuid.UUID,
    payload: ProjectDeploymentPreflightRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    errors: list[str] = []
    warnings: list[str] = []
    provider = (payload.provider or "").strip().lower()
    if provider not in {"vercel", "render"}:
        errors.append("Unsupported provider")
    env_name = (payload.environment or "PREVIEW").strip().upper()
    if env_name not in {"PREVIEW", "STAGING", "PRODUCTION"}:
        errors.append("Invalid environment")
    strategy = (payload.deployment_strategy or "static_frontend").strip().lower()
    if strategy not in {"static_frontend", "fullstack_web", "api_service", "worker_service", "monorepo_split"}:
        warnings.append("Unknown deployment strategy; default runtime assumptions may be weak.")
    profile = await session.scalar(
        select(DeploymentProfile).where(
            DeploymentProfile.tenant_id == ctx.tenant_id,
            DeploymentProfile.project_id == project_id,
            DeploymentProfile.environment == env_name,
        )
    )
    if profile is None:
        errors.append("No deployment profile found for environment.")
    else:
        if not profile.provider_connector_id:
            errors.append("Deployment profile missing provider connector.")
        if not (profile.build_command or "").strip():
            warnings.append("build_command missing in deployment profile.")
        if not (profile.healthcheck_path or "").strip():
            warnings.append("healthcheck_path missing in deployment profile.")
    ok = not errors
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "provider": provider,
        "environment": env_name,
        "deployment_strategy": strategy,
    }


@router.get("/projects/{project_id}/deployments/intelligence", response_model=DeploymentIntelligenceOut)
@public_router.get("/projects/{project_id}/deployments/intelligence", response_model=DeploymentIntelligenceOut)
async def deployment_intelligence(
    project_id: uuid.UUID,
    limit: int = Query(default=80, ge=10, le=300),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> DeploymentIntelligenceOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(ProjectDeployment)
        .where(ProjectDeployment.tenant_id == ctx.tenant_id, ProjectDeployment.project_id == project_id)
        .order_by(ProjectDeployment.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    if not rows:
        return DeploymentIntelligenceOut(project_id=project_id)

    total = len(rows)
    ready_count = sum(1 for row in rows if str(row.status).upper() == "READY")
    avg_confidence = sum(float(row.deployment_confidence_score or 0.0) for row in rows) / total
    success_rate = ready_count / total if total else 0.0

    failures: dict[str, int] = {}
    manual_reasons: list[str] = []
    trend: list[dict] = []
    for row in reversed(rows):
        status = str(row.status or "").upper()
        if "FAILED" in status or status == "MANUAL_ACTION_REQUIRED":
            key = status
            if row.error_message:
                lowered = str(row.error_message).lower()
                if "health" in lowered:
                    key = "deploy_health_failed"
                elif "missing" in lowered and "env" in lowered:
                    key = "deploy_env_missing"
                elif "provider" in lowered:
                    key = "deploy_provider_unreachable"
                elif "timeout" in lowered:
                    key = "deploy_timeout"
            failures[key] = failures.get(key, 0) + 1
        if status == "MANUAL_ACTION_REQUIRED" and row.error_message:
            manual_reasons.append(str(row.error_message))
        trend.append({
            "deployment_id": str(row.id),
            "status": status,
            "confidence": float(row.deployment_confidence_score or 0.0),
            "created_at": row.created_at,
        })

    top_failure_clusters = [
        {"cluster": key, "count": count}
        for key, count in sorted(failures.items(), key=lambda item: item[1], reverse=True)[:5]
    ]

    return DeploymentIntelligenceOut(
        project_id=project_id,
        total_deployments=total,
        success_rate=success_rate,
        avg_confidence=avg_confidence,
        top_failure_clusters=top_failure_clusters,
        confidence_trend=trend[-30:],
        recent_manual_degrade_reasons=manual_reasons[:5],
    )


@router.post("/projects/{project_id}/deployment-profile", response_model=DeploymentProfileOut)
@public_router.post("/projects/{project_id}/deployment-profile", response_model=DeploymentProfileOut)
async def upsert_deployment_profile(
    project_id: uuid.UUID,
    payload: DeploymentProfileUpsertRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> DeploymentProfileOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    environment = (payload.environment or "PREVIEW").strip().upper()
    profile = await session.scalar(
        select(DeploymentProfile).where(
            DeploymentProfile.tenant_id == ctx.tenant_id,
            DeploymentProfile.project_id == project_id,
            DeploymentProfile.environment == environment,
        )
    )
    if profile is None:
        profile = DeploymentProfile(
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            environment=environment,
            created_by=(payload.created_by or ctx.user_id or "ui-user"),
        )
        session.add(profile)
    if payload.provider_connector_id:
        connector = await session.scalar(
            select(DeploymentProviderConnector).where(
                DeploymentProviderConnector.id == payload.provider_connector_id,
                DeploymentProviderConnector.tenant_id == ctx.tenant_id,
            )
        )
        if connector is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment connector not found")
    profile.provider = (payload.provider or profile.provider or "vercel").strip().lower()
    profile.deployment_strategy = (payload.deployment_strategy or profile.deployment_strategy or "static_frontend").strip().lower()
    profile.framework = payload.framework
    profile.install_command = payload.install_command
    profile.build_command = payload.build_command
    profile.output_dir = payload.output_dir
    profile.start_command = payload.start_command
    profile.healthcheck_path = payload.healthcheck_path
    profile.region = payload.region
    profile.runtime_version = payload.runtime_version
    profile.env_schema = payload.env_schema
    profile.provider_connector_id = payload.provider_connector_id
    await session.commit()
    await session.refresh(profile)
    return DeploymentProfileOut.model_validate(profile)


@router.get("/projects/{project_id}/deployment-profile", response_model=DeploymentProfileOut)
@public_router.get("/projects/{project_id}/deployment-profile", response_model=DeploymentProfileOut)
async def get_deployment_profile(
    project_id: uuid.UUID,
    environment: str = Query(default="PREVIEW"),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> DeploymentProfileOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    env_name = (environment or "PREVIEW").strip().upper()
    profile = await session.scalar(
        select(DeploymentProfile).where(
            DeploymentProfile.tenant_id == ctx.tenant_id,
            DeploymentProfile.project_id == project_id,
            DeploymentProfile.environment == env_name,
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment profile not found")
    return DeploymentProfileOut.model_validate(profile)


@router.post("/deployment-connectors", response_model=DeploymentProviderConnectorOut)
@public_router.post("/deployment-connectors", response_model=DeploymentProviderConnectorOut)
async def upsert_deployment_connector(
    payload: DeploymentProviderConnectorUpsertRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> DeploymentProviderConnectorOut:
    provider = (payload.provider or "").strip().lower()
    label = (payload.label or "").strip()
    vault_ref = (payload.vault_ref or "").strip()
    if not provider or not label or not vault_ref:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider, label, and vault_ref are required")
    connector = await session.scalar(
        select(DeploymentProviderConnector).where(
            DeploymentProviderConnector.tenant_id == ctx.tenant_id,
            DeploymentProviderConnector.provider == provider,
            DeploymentProviderConnector.label == label,
        )
    )
    if connector is None:
        connector = DeploymentProviderConnector(
            tenant_id=ctx.tenant_id,
            provider=provider,
            label=label,
            created_by=(payload.created_by or ctx.user_id or "ui-user"),
        )
        session.add(connector)
    connector.vault_ref = vault_ref
    connector.scopes = payload.scopes
    await session.commit()
    await session.refresh(connector)
    return DeploymentProviderConnectorOut.model_validate(connector)


@router.get("/deployment-connectors", response_model=List[DeploymentProviderConnectorOut])
@public_router.get("/deployment-connectors", response_model=List[DeploymentProviderConnectorOut])
async def list_deployment_connectors(
    provider: str | None = None,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[DeploymentProviderConnectorOut]:
    query = select(DeploymentProviderConnector).where(DeploymentProviderConnector.tenant_id == ctx.tenant_id)
    if provider:
        query = query.where(DeploymentProviderConnector.provider == provider.strip().lower())
    result = await session.execute(query.order_by(DeploymentProviderConnector.created_at.desc()))
    return [DeploymentProviderConnectorOut.model_validate(item) for item in result.scalars().all()]


@public_router.post("/auth/bootstrap-first-login", response_model=FirstLoginBootstrapOut)
async def bootstrap_first_login(
    payload: FirstLoginBootstrapRequest,
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> FirstLoginBootstrapOut:
    token = _extract_bearer_token_or_401(authorization)
    try:
        claims = verify_firebase_bearer_token(token, project_id=str(settings.firebase_project_id or ""))
    except FirebaseAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": str(exc) or "Authentication token is invalid."},
        ) from exc

    user_id = _user_id_from_claims(claims)
    email = claims.get("email") if isinstance(claims.get("email"), str) else ""
    base_name = email.split("@")[0].strip() if email and "@" in email else "Operator"
    tenant_default_name = f"{base_name or 'Operator'} Workspace"
    workspace_default_name = "Default Workspace"

    created_tenant = False
    created_workspace = False
    created_tenant_member = False
    created_workspace_member = False

    tenant_member = None
    if not payload.force_new_tenant:
        tenant_member = await session.scalar(
            select(TenantMember).where(TenantMember.user_id == user_id).order_by(TenantMember.created_at.asc())
        )
    tenant: Tenant | None = None
    if tenant_member:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_member.tenant_id))

    if tenant is None:
        tenant = Tenant(name=_sanitize_entity_name(payload.tenant_name, tenant_default_name))
        session.add(tenant)
        await session.flush()
        created_tenant = True

    if tenant_member is None:
        tenant_member = TenantMember(tenant_id=tenant.id, user_id=user_id, role="OWNER")
        session.add(tenant_member)
        await session.flush()
        created_tenant_member = True

    workspace = await session.scalar(
        select(Workspace).where(Workspace.tenant_id == tenant.id).order_by(Workspace.created_at.asc())
    )
    if workspace is None:
        workspace = Workspace(tenant_id=tenant.id, name=_sanitize_entity_name(payload.workspace_name, workspace_default_name))
        session.add(workspace)
        await session.flush()
        created_workspace = True

    workspace_member = await session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user_id)
    )
    if workspace_member is None:
        workspace_member = WorkspaceMember(workspace_id=workspace.id, user_id=user_id, role="OWNER")
        session.add(workspace_member)
        await session.flush()
        created_workspace_member = True

    await session.commit()

    return FirstLoginBootstrapOut(
        user_id=user_id,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        tenant_member_role=tenant_member.role,
        workspace_member_role=workspace_member.role,
        created_tenant=created_tenant,
        created_workspace=created_workspace,
        created_tenant_member=created_tenant_member,
        created_workspace_member=created_workspace_member,
    )


@router.get("/workspaces", response_model=List[WorkspaceOut])
@public_router.get("/workspaces", response_model=List[WorkspaceOut])
async def list_workspaces(
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[WorkspaceOut]:
    result = await session.execute(
        select(Workspace)
        .where(Workspace.tenant_id == ctx.tenant_id)
        .order_by(Workspace.created_at.asc())
    )
    return [WorkspaceOut.model_validate(item) for item in result.scalars().all()]


@router.get("/workspaces/{workspace_id}/switch", response_model=WorkspaceSwitchOut)
@public_router.get("/workspaces/{workspace_id}/switch", response_model=WorkspaceSwitchOut)
async def switch_workspace(
    workspace_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceSwitchOut:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == ctx.tenant_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == ctx.user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace membership required")
    projects = (
        await session.execute(
            select(Project)
            .where(Project.tenant_id == ctx.tenant_id, Project.workspace_id == workspace_id)
            .order_by(Project.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return WorkspaceSwitchOut(
        workspace=WorkspaceOut.model_validate(workspace),
        projects=[_project_out(project) for project in projects],
    )


@router.get("/workspaces/{workspace_id}/entitlements", response_model=WorkspaceEntitlementOut)
@public_router.get("/workspaces/{workspace_id}/entitlements", response_model=WorkspaceEntitlementOut)
async def get_workspace_entitlements(
    workspace_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceEntitlementOut:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == ctx.tenant_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == ctx.user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace membership required")
    entitlement = await _ensure_workspace_entitlement(session, ctx, workspace_id)
    return WorkspaceEntitlementOut.model_validate(entitlement)


@router.get("/workspaces/{workspace_id}/usage", response_model=WorkspaceUsageSummaryOut)
@public_router.get("/workspaces/{workspace_id}/usage", response_model=WorkspaceUsageSummaryOut)
async def get_workspace_usage(
    workspace_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=90),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceUsageSummaryOut:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == ctx.tenant_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == ctx.user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace membership required")

    return await _load_workspace_usage_summary(
        session=session,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        days=days,
    )


@router.post("/workspaces/{workspace_id}/usage/materialize", response_model=WorkspaceUsageMaterializeOut)
@public_router.post("/workspaces/{workspace_id}/usage/materialize", response_model=WorkspaceUsageMaterializeOut)
async def materialize_workspace_usage(
    workspace_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=90),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceUsageMaterializeOut:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == ctx.tenant_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == ctx.user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace membership required")
    summary = await _load_workspace_usage_summary(
        session=session,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        days=days,
    )
    rows_upserted = 0
    for row in summary.daily:
        usage_date = datetime.fromisoformat(row.usage_date).date()
        record = await session.scalar(
            select(WorkspaceUsageDaily).where(
                WorkspaceUsageDaily.workspace_id == workspace_id,
                WorkspaceUsageDaily.tenant_id == ctx.tenant_id,
                WorkspaceUsageDaily.usage_date == usage_date,
            )
        )
        if record is None:
            record = WorkspaceUsageDaily(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                usage_date=usage_date,
            )
            session.add(record)
        record.runs_count = row.runs_count
        record.deployments_count = row.deployments_count
        record.recoveries_count = row.recoveries_count
        record.input_tokens = row.input_tokens
        record.output_tokens = row.output_tokens
        record.total_cost_cents = row.total_cost_cents
        rows_upserted += 1
    await session.commit()
    return WorkspaceUsageMaterializeOut(
        workspace_id=workspace_id,
        days=days,
        rows_upserted=rows_upserted,
        totals=summary.totals,
    )


@router.get("/workspaces/{workspace_id}/environment-checklists", response_model=list[EnvironmentChecklistSummaryOut])
@public_router.get("/workspaces/{workspace_id}/environment-checklists", response_model=list[EnvironmentChecklistSummaryOut])
async def list_workspace_environment_checklists(
    workspace_id: uuid.UUID,
    reseed: bool = Query(default=False),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[EnvironmentChecklistSummaryOut]:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == ctx.tenant_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == ctx.user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace membership required")

    projects = (
        await session.execute(
            select(Project)
            .where(
                Project.tenant_id == ctx.tenant_id,
                or_(Project.workspace_id == workspace_id, Project.workspace_id.is_(None)),
            )
            .order_by(Project.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    payload: list[EnvironmentChecklistSummaryOut] = []
    for project in projects:
        payload.append(await _load_environment_checklists(session, ctx=ctx, project=project, reseed=reseed))
    return payload


@router.get("/admin/workspaces", response_model=List[AdminWorkspaceOut])
@public_router.get("/admin/workspaces", response_model=List[AdminWorkspaceOut])
async def list_admin_workspaces(
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[AdminWorkspaceOut]:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspaces = (
        await session.execute(
            select(Workspace)
            .where(Workspace.tenant_id == ctx.tenant_id)
            .order_by(Workspace.created_at.asc())
        )
    ).scalars().all()
    if not workspaces:
        return []
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    response: list[AdminWorkspaceOut] = []
    for workspace in workspaces:
        project_ids = (
            await session.execute(
                select(Project.id).where(Project.tenant_id == ctx.tenant_id, Project.workspace_id == workspace.id)
            )
        ).scalars().all()
        if project_ids:
            run_rows = (
                await session.execute(
                    select(Run.status)
                    .where(Run.tenant_id == ctx.tenant_id, Run.project_id.in_(project_ids), Run.created_at >= week_ago)
                )
            ).all()
        else:
            run_rows = []
        run_count_7d = len(run_rows)
        failed_run_count_7d = sum(1 for row in run_rows if str(row.status).upper() == "FAILED")
        response.append(
            AdminWorkspaceOut(
                workspace=WorkspaceOut.model_validate(workspace),
                project_count=len(project_ids),
                run_count_7d=run_count_7d,
                failed_run_count_7d=failed_run_count_7d,
            )
        )
    return response


@router.get("/admin/system-config", response_model=list[PlatformConfigOut])
@public_router.get("/admin/system-config", response_model=list[PlatformConfigOut])
async def list_admin_system_config(
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[PlatformConfigOut]:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    rows = (await session.execute(select(PlatformConfig).order_by(PlatformConfig.config_key.asc()))).scalars().all()
    return [_platform_config_out(row) for row in rows]


@router.put("/admin/system-config/{config_key}", response_model=PlatformConfigOut)
@public_router.put("/admin/system-config/{config_key}", response_model=PlatformConfigOut)
async def upsert_admin_system_config(
    config_key: str,
    payload: PlatformConfigUpsertRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> PlatformConfigOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    key = config_key.strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="config_key is required")
    value_type = (payload.value_type or "string").strip().lower()
    if value_type not in {"string", "json", "secret_ref", "bool", "number"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported value_type")
    if value_type == "secret_ref" and not (payload.vault_ref or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="vault_ref is required for secret_ref values")

    row = await session.scalar(select(PlatformConfig).where(PlatformConfig.config_key == key))
    if row is None:
        row = PlatformConfig(config_key=key)
    row.config_scope = "global"
    row.value_type = value_type
    if value_type == "secret_ref":
        row.plain_value = None
    else:
        row.plain_value = payload.plain_value
    row.vault_ref = (payload.vault_ref or "").strip() or None
    row.description = (payload.description or "").strip() or None
    row.updated_by = ctx.user_id
    session.add(row)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            action="platform_config.upsert",
            reason=(payload.reason or "").strip() or None,
            extra_metadata={"config_key": key, "value_type": value_type, "has_vault_ref": bool(row.vault_ref)},
        )
    )
    await session.commit()
    await session.refresh(row)
    return _platform_config_out(row)


@router.post("/admin/system-config/{config_key}/rotate", response_model=PlatformConfigOut)
@public_router.post("/admin/system-config/{config_key}/rotate", response_model=PlatformConfigOut)
async def rotate_admin_system_config(
    config_key: str,
    payload: PlatformConfigRotateRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> PlatformConfigOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    key = config_key.strip()
    row = await session.scalar(select(PlatformConfig).where(PlatformConfig.config_key == key))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System config not found")
    row.vault_ref = payload.vault_ref.strip()
    row.value_type = "secret_ref"
    row.updated_by = ctx.user_id
    session.add(row)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            action="platform_config.rotate",
            reason=(payload.reason or "").strip() or None,
            extra_metadata={"config_key": key, "vault_ref": row.vault_ref},
        )
    )
    await session.commit()
    await session.refresh(row)
    return _platform_config_out(row)


@router.get("/admin/workspaces/{workspace_id}", response_model=AdminWorkspaceOut)
@public_router.get("/admin/workspaces/{workspace_id}", response_model=AdminWorkspaceOut)
async def get_admin_workspace_detail(
    workspace_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> AdminWorkspaceOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == ctx.tenant_id)
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    project_ids = (
        await session.execute(
            select(Project.id).where(Project.tenant_id == ctx.tenant_id, Project.workspace_id == workspace.id)
        )
    ).scalars().all()
    run_rows = []
    if project_ids:
        run_rows = (
            await session.execute(
                select(Run.status)
                .where(Run.tenant_id == ctx.tenant_id, Run.project_id.in_(project_ids), Run.created_at >= week_ago)
            )
        ).all()
    return AdminWorkspaceOut(
        workspace=WorkspaceOut.model_validate(workspace),
        project_count=len(project_ids),
        run_count_7d=len(run_rows),
        failed_run_count_7d=sum(1 for row in run_rows if str(row.status).upper() == "FAILED"),
    )


@router.post("/admin/impersonation/start", response_model=AdminImpersonationOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/admin/impersonation/start", response_model=AdminImpersonationOut, status_code=status.HTTP_201_CREATED)
async def start_admin_impersonation(
    payload: AdminImpersonationStartRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> AdminImpersonationOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == payload.workspace_id, Workspace.tenant_id == ctx.tenant_id)
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=payload.duration_minutes)
    record = ImpersonationSession(
        admin_user_id=ctx.user_id,
        target_workspace_id=payload.workspace_id,
        reason=(payload.reason or "").strip() or None,
        expires_at=expires_at,
        is_active=True,
    )
    session.add(record)
    audit = AdminAuditLog(
        admin_user_id=ctx.user_id,
        target_workspace_id=payload.workspace_id,
        action="impersonation.start",
        reason=(payload.reason or "").strip() or None,
        extra_metadata={"duration_minutes": payload.duration_minutes},
    )
    session.add(audit)
    await session.commit()
    await session.refresh(record)
    return AdminImpersonationOut.model_validate(record)


@router.post("/admin/impersonation/{session_id}/end", response_model=AdminImpersonationOut)
@public_router.post("/admin/impersonation/{session_id}/end", response_model=AdminImpersonationOut)
async def end_admin_impersonation(
    session_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> AdminImpersonationOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    record = await session.scalar(select(ImpersonationSession).where(ImpersonationSession.id == session_id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Impersonation session not found")
    if record.is_active:
        now = datetime.now(timezone.utc)
        record.is_active = False
        record.ended_at = now
        record.ended_by = ctx.user_id
        if record.started_at:
            started_at = record.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            duration_seconds = int((now - started_at).total_seconds())
        else:
            duration_seconds = None
    else:
        duration_seconds = None
    audit = AdminAuditLog(
        admin_user_id=ctx.user_id,
        target_workspace_id=record.target_workspace_id,
        action="impersonation.end",
        duration_seconds=duration_seconds,
        extra_metadata={"impersonation_session_id": str(record.id), "ended_by": ctx.user_id},
    )
    session.add(record)
    session.add(audit)
    await session.commit()
    await session.refresh(record)
    return AdminImpersonationOut.model_validate(record)


@router.get("/admin/audit-logs", response_model=List[AdminAuditLogOut])
@public_router.get("/admin/audit-logs", response_model=List[AdminAuditLogOut])
async def list_admin_audit_logs(
    workspace_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[AdminAuditLogOut]:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    query = select(AdminAuditLog).where(AdminAuditLog.admin_user_id != "")
    if workspace_id is not None:
        query = query.where(AdminAuditLog.target_workspace_id == workspace_id)
    result = await session.execute(query.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).limit(limit))
    rows = result.scalars().all()
    return [AdminAuditLogOut.model_validate(row) for row in rows]


@router.get("/admin/daemon-health", response_model=AdminDaemonHealthOut)
@public_router.get("/admin/daemon-health", response_model=AdminDaemonHealthOut)
async def get_admin_daemon_health(
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> AdminDaemonHealthOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    latest_cycle = await session.scalar(
        select(AdminAuditLog)
        .where(
            AdminAuditLog.action == "workspace_ops.cycle",
        )
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .limit(1)
    )
    latest_error = await session.scalar(
        select(AdminAuditLog)
        .where(
            AdminAuditLog.action == "workspace_ops.workspace_error",
        )
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .limit(1)
    )
    cycle_meta = latest_cycle.extra_metadata if latest_cycle and isinstance(latest_cycle.extra_metadata, dict) else {}
    alert_reasons: list[str] = []
    current_settings = get_settings()
    if int(cycle_meta.get("workspace_failures") or 0) > 0:
        alert_reasons.append("latest_cycle_has_workspace_failures")
    if latest_cycle and latest_cycle.created_at:
        interval_seconds = max(300, int(current_settings.workspace_ops_daemon_interval_seconds))
        stale_after_seconds = interval_seconds * 2
        cycle_at = latest_cycle.created_at
        if cycle_at.tzinfo is None:
            cycle_at = cycle_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - cycle_at).total_seconds()
        if age_seconds > stale_after_seconds:
            alert_reasons.append("daemon_cycle_stale")
    elif latest_cycle is None:
        alert_reasons.append("no_daemon_cycle_recorded")
    alert_level = "warn" if alert_reasons else "healthy"
    return AdminDaemonHealthOut(
        last_cycle_at=latest_cycle.created_at if latest_cycle else None,
        last_cycle_window_days=int(cycle_meta.get("window_days") or 0) or None,
        last_cycle_workspaces_processed=int(cycle_meta.get("workspaces_processed") or 0),
        last_cycle_workspace_failures=int(cycle_meta.get("workspace_failures") or 0),
        last_error_at=latest_error.created_at if latest_error else None,
        last_error_workspace_id=latest_error.target_workspace_id if latest_error else None,
        alert_level=alert_level,
        alert_reasons=alert_reasons,
    )


@router.get("/admin/workspaces/{workspace_id}/entitlements", response_model=WorkspaceEntitlementOut)
@public_router.get("/admin/workspaces/{workspace_id}/entitlements", response_model=WorkspaceEntitlementOut)
async def get_admin_workspace_entitlements(
    workspace_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceEntitlementOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == ctx.tenant_id)
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    entitlement = await _ensure_workspace_entitlement(session, ctx, workspace_id)
    return WorkspaceEntitlementOut.model_validate(entitlement)


@router.patch("/admin/workspaces/{workspace_id}/entitlements", response_model=WorkspaceEntitlementOut)
@public_router.patch("/admin/workspaces/{workspace_id}/entitlements", response_model=WorkspaceEntitlementOut)
async def patch_admin_workspace_entitlements(
    workspace_id: uuid.UUID,
    payload: AdminWorkspaceEntitlementPatchRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceEntitlementOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == ctx.tenant_id)
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    entitlement = await _ensure_workspace_entitlement(session, ctx, workspace_id)
    if payload.plan is not None:
        entitlement.plan = payload.plan.strip() or entitlement.plan
    if payload.limits is not None:
        entitlement.limits = payload.limits
    if payload.features is not None:
        entitlement.features = payload.features
    session.add(entitlement)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=workspace_id,
            action="entitlement.update",
            extra_metadata={
                "plan": entitlement.plan,
                "limits_keys": sorted(list((entitlement.limits or {}).keys())),
                "features_keys": sorted(list((entitlement.features or {}).keys())),
            },
        )
    )
    await session.commit()
    await session.refresh(entitlement)
    return WorkspaceEntitlementOut.model_validate(entitlement)


@router.get("/admin/workspaces/{workspace_id}/usage", response_model=WorkspaceUsageSummaryOut)
@public_router.get("/admin/workspaces/{workspace_id}/usage", response_model=WorkspaceUsageSummaryOut)
async def get_admin_workspace_usage(
    workspace_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=90),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceUsageSummaryOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == ctx.tenant_id)
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return await _load_workspace_usage_summary(
        session=session,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        days=days,
    )


@router.post("/admin/workspaces/{workspace_id}/usage/materialize", response_model=WorkspaceUsageMaterializeOut)
@public_router.post("/admin/workspaces/{workspace_id}/usage/materialize", response_model=WorkspaceUsageMaterializeOut)
async def materialize_admin_workspace_usage(
    workspace_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=90),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceUsageMaterializeOut:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.tenant_id == ctx.tenant_id)
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    summary = await _load_workspace_usage_summary(
        session=session,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        days=days,
    )
    rows_upserted = 0
    for row in summary.daily:
        usage_date = datetime.fromisoformat(row.usage_date).date()
        record = await session.scalar(
            select(WorkspaceUsageDaily).where(
                WorkspaceUsageDaily.workspace_id == workspace_id,
                WorkspaceUsageDaily.tenant_id == ctx.tenant_id,
                WorkspaceUsageDaily.usage_date == usage_date,
            )
        )
        if record is None:
            record = WorkspaceUsageDaily(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace_id,
                usage_date=usage_date,
            )
            session.add(record)
        record.runs_count = row.runs_count
        record.deployments_count = row.deployments_count
        record.recoveries_count = row.recoveries_count
        record.input_tokens = row.input_tokens
        record.output_tokens = row.output_tokens
        record.total_cost_cents = row.total_cost_cents
        rows_upserted += 1
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            target_workspace_id=workspace_id,
            action="usage.materialize",
            extra_metadata={"days": days, "rows_upserted": rows_upserted},
        )
    )
    await session.commit()
    return WorkspaceUsageMaterializeOut(
        workspace_id=workspace_id,
        days=days,
        rows_upserted=rows_upserted,
        totals=summary.totals,
    )


@router.post("/admin/anomalies/materialize", response_model=List[WorkspaceAnomalySnapshotOut])
@public_router.post("/admin/anomalies/materialize", response_model=List[WorkspaceAnomalySnapshotOut])
async def materialize_workspace_anomalies(
    days: int = Query(default=30, ge=7, le=90),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[WorkspaceAnomalySnapshotOut]:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    workspaces = (
        await session.execute(select(Workspace).where(Workspace.tenant_id == ctx.tenant_id).order_by(Workspace.created_at.asc()))
    ).scalars().all()
    today = datetime.now(timezone.utc).date()
    snapshots: list[WorkspaceAnomalySnapshot] = []
    for workspace in workspaces:
        summary = await _load_workspace_usage_summary(
            session=session,
            tenant_id=ctx.tenant_id,
            workspace_id=workspace.id,
            days=days,
        )
        burn_spike, failure_spike, burn_ratio, failure_ratio = _compute_usage_anomaly_flags(summary.daily)
        total_tokens = int(summary.totals.input_tokens or 0) + int(summary.totals.output_tokens or 0)
        snapshot = await session.scalar(
            select(WorkspaceAnomalySnapshot).where(
                WorkspaceAnomalySnapshot.tenant_id == ctx.tenant_id,
                WorkspaceAnomalySnapshot.workspace_id == workspace.id,
                WorkspaceAnomalySnapshot.window_days == days,
                WorkspaceAnomalySnapshot.snapshot_date == today,
            )
        )
        if snapshot is None:
            snapshot = WorkspaceAnomalySnapshot(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace.id,
                snapshot_date=today,
                window_days=days,
            )
            session.add(snapshot)
        snapshot.runs_count = int(summary.totals.runs_count or 0)
        snapshot.recoveries_count = int(summary.totals.recoveries_count or 0)
        snapshot.total_tokens = total_tokens
        snapshot.total_cost_cents = int(summary.totals.total_cost_cents or 0)
        snapshot.burn_spike = burn_spike
        snapshot.failure_spike = failure_spike
        snapshot.burn_ratio = burn_ratio
        snapshot.failure_ratio = failure_ratio
        snapshots.append(snapshot)
    session.add(
        AdminAuditLog(
            admin_user_id=ctx.user_id,
            action="anomaly.materialize",
            extra_metadata={"days": days, "workspace_count": len(workspaces)},
        )
    )
    await session.commit()
    for row in snapshots:
        await session.refresh(row)
    return [WorkspaceAnomalySnapshotOut.model_validate(row) for row in snapshots]


@router.get("/admin/anomalies", response_model=List[WorkspaceAnomalySnapshotOut])
@public_router.get("/admin/anomalies", response_model=List[WorkspaceAnomalySnapshotOut])
async def list_workspace_anomaly_snapshots(
    workspace_id: uuid.UUID | None = None,
    days: int = Query(default=30, ge=7, le=90),
    limit: int = Query(default=50, ge=1, le=500),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[WorkspaceAnomalySnapshotOut]:
    if not _is_super_admin(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    query = select(WorkspaceAnomalySnapshot).where(
        WorkspaceAnomalySnapshot.tenant_id == ctx.tenant_id,
        WorkspaceAnomalySnapshot.window_days == days,
    )
    if workspace_id is not None:
        query = query.where(WorkspaceAnomalySnapshot.workspace_id == workspace_id)
    rows = (
        await session.execute(
            query.order_by(WorkspaceAnomalySnapshot.snapshot_date.desc(), WorkspaceAnomalySnapshot.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [WorkspaceAnomalySnapshotOut.model_validate(row) for row in rows]


@router.get("/runs/{run_id}/events", response_model=List[RunEventOut])
@public_router.get("/runs/{run_id}/events", response_model=List[RunEventOut])
async def list_run_events(run_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)) -> List[RunEventOut]:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    result = await session.execute(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.tenant_id == ctx.tenant_id)
        .order_by(RunEvent.ts.asc(), RunEvent.id.asc())
    )
    events = result.scalars().all()
    return [RunEventOut.model_validate(ev) for ev in events]


# WorkItems
@router.get("/projects/{project_id}/runs/{run_id}/work-items", response_model=List[WorkItemOut])
@public_router.get("/projects/{project_id}/runs/{run_id}/work-items", response_model=List[WorkItemOut])
async def list_work_items(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[WorkItemOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    result = await session.execute(
        select(WorkItem)
        .where(WorkItem.run_id == run_id, WorkItem.tenant_id == ctx.tenant_id)
        .order_by(WorkItem.created_at)
    )
    return [_wi_out(wi) for wi in result.scalars().all()]


@router.get("/work-items/{work_item_id}", response_model=WorkItemOut)
async def get_work_item(work_item_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)) -> WorkItemOut:
    wi = await session.scalar(_wi_scoped(session, ctx, work_item_id))
    if not wi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    return _wi_out(wi)


@router.get("/runs/{run_id}/work-dag")
@public_router.get("/runs/{run_id}/work-dag")
async def get_work_dag(run_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)) -> dict:
    run = await session.scalar(_run_scoped(session, ctx, run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    nodes = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run_id, WorkItem.tenant_id == ctx.tenant_id)
            .order_by(WorkItem.created_at)
        )
    ).scalars().all()
    edges = (
        await session.execute(
            select(WorkItemEdge).where(WorkItemEdge.run_id == run_id, WorkItemEdge.tenant_id == ctx.tenant_id)
        )
    ).scalars().all()
    return {
        "nodes": [_wi_out(n) for n in nodes],
        "edges": [{"from_work_item_id": e.from_work_item_id, "to_work_item_id": e.to_work_item_id} for e in edges],
    }


# Agents
@router.post("/agents/register", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def register_agent(payload: AgentCreate, session: AsyncSession = Depends(get_session)) -> AgentOut:
    agent = Agent(
        name=payload.name,
        kind=payload.kind,
        executors=payload.executors or [],
        max_concurrency=payload.max_concurrency,
        capabilities=payload.capabilities or {},
        status="ACTIVE",
    )
    async with session.begin():
        session.add(agent)
    await session.refresh(agent)
    return AgentOut.model_validate(agent)


@router.post("/agents/{agent_id}/heartbeat", response_model=AgentOut)
async def agent_heartbeat(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> AgentOut:
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent.last_heartbeat_at = datetime.now(timezone.utc)
    async with session.begin():
        session.add(agent)
    await session.refresh(agent)
    return AgentOut.model_validate(agent)


@router.get("/agents", response_model=List[AgentOut])
async def list_agents(session: AsyncSession = Depends(get_session)) -> List[AgentOut]:
    result = await session.execute(select(Agent).order_by(Agent.created_at.desc()))
    return [AgentOut.model_validate(a) for a in result.scalars().all()]


# External worker interaction
@router.post("/agents/{agent_id}/claim")
async def claim_work_items(
    agent_id: uuid.UUID,
    payload: ClaimRequest,
    session: AsyncSession = Depends(get_session),
):
    if settings.runtime_mode == "embedded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Claiming work items is disabled in embedded mode.",
        )
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    limit = max(1, min(payload.limit, agent.max_concurrency or 1))
    lease_seconds = max(10, min(payload.lease_seconds, 600))
    now = datetime.now(timezone.utc)
    lease_expires = now + timedelta(seconds=lease_seconds)

    from sqlalchemy.orm import aliased
    parent = aliased(WorkItem)
    blocking_exists = exists(
        select(1)
        .select_from(WorkItemEdge)
        .join(parent, parent.id == WorkItemEdge.from_work_item_id)
        .where(WorkItemEdge.to_work_item_id == WorkItem.id, parent.status.notin_(["DONE", "SKIPPED"]))
    )

    result = await session.execute(
        select(WorkItem)
        .join(Run, Run.id == WorkItem.run_id)
        .where(
            WorkItem.status == "QUEUED",
            Run.status.in_(["RUNNING", "QUEUED"]),
            ~blocking_exists,
        )
        .order_by(WorkItem.priority.desc(), WorkItem.created_at)
        .limit(limit * 2)
    )
    items = result.scalars().all()
    claimed = []
    agent_caps = set(agent.capabilities or [])
    async with session.begin():
        for wi in items:
            active_run = await session.scalar(
                select(Run)
                .where(Run.id == wi.run_id, Run.status.in_(["RUNNING", "QUEUED"]))
                .with_for_update(skip_locked=True)
            )
            if active_run is None:
                continue
            req_caps = set(wi.required_capabilities or [])
            if req_caps and not req_caps.issubset(agent_caps):
                continue
            ok = await update_work_item_status(
                session,
                wi.id,
                ["QUEUED"],
                "RUNNING",
                assigned_agent_id=agent_id,
                lease_expires_at=lease_expires,
                started_at=now,
            )
            if not ok:
                continue
            fresh = await session.get(WorkItem, wi.id)
            if not fresh:
                continue
            await record_event(
                session,
                project_id=fresh.project_id,
                run_id=fresh.run_id,
                work_item_id=fresh.id,
                event_type="WORK_ITEM_CLAIMED",
                actor_type="AGENT",
                actor_id=str(agent_id),
                payload={"work_item_id": str(fresh.id), "agent_id": str(agent_id)},
            )
            await record_event(
                session,
                project_id=fresh.project_id,
                run_id=fresh.run_id,
                work_item_id=fresh.id,
                event_type="RUN_WORKER_PICKED",
                actor_type="AGENT",
                actor_id=str(agent_id),
                payload={"work_item_id": str(fresh.id), "agent_id": str(agent_id)},
            )
            claimed.append(fresh)
            if len(claimed) >= limit:
                break
    return [_wi_out(wi) for wi in claimed]


@router.post("/work-items/{work_item_id}/complete", response_model=WorkItemOut)
async def complete_work_item(
    work_item_id: uuid.UUID,
    payload: WorkItemComplete,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    result = await session.execute(
        select(WorkItem).where(WorkItem.id == work_item_id, WorkItem.status == "RUNNING").with_for_update(skip_locked=True)
    )
    wi = result.scalar_one_or_none()
    if not wi:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item not runnable or already finished.")
    now = datetime.now(timezone.utc)
    if wi.lease_expires_at and wi.lease_expires_at < now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lease expired; please re-claim the work item.")
    terminal_status = payload.status.upper()
    ok = await update_work_item_status(
        session,
        wi.id,
        ["RUNNING"],
        terminal_status,
        result=payload.result,
        finished_at=now,
        last_error=None,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unable to complete work item (state changed).")
    wi = await session.get(WorkItem, wi.id)
    async with session.begin():
        await persist_work_item_artifacts(session, wi, payload.artifacts)
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_SKIPPED" if terminal_status == "SKIPPED" else "WORK_ITEM_DONE",
            actor_type="AGENT",
            payload={"work_item_id": str(wi.id), "status": terminal_status},
        )
        await maybe_apply_recovery(session, wi)
        await _maybe_finalize_run(session, wi.run_id)
    await session.refresh(wi)
    return _wi_out(wi)


@router.post("/work-items/{work_item_id}/fail", response_model=WorkItemOut)
async def fail_work_item(
    work_item_id: uuid.UUID,
    payload: WorkItemFail,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    result = await session.execute(
        select(WorkItem).where(WorkItem.id == work_item_id, WorkItem.status == "RUNNING").with_for_update(skip_locked=True)
    )
    wi = result.scalar_one_or_none()
    if not wi:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item not runnable or already finished.")
    now = datetime.now(timezone.utc)
    if wi.lease_expires_at and wi.lease_expires_at < now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lease expired; please re-claim the work item.")
    retrying = payload.retry and wi.attempt + 1 < wi.max_attempts
    if retrying:
        ok = await update_work_item_status(
            session,
            wi.id,
            ["RUNNING"],
            "QUEUED",
            attempt=wi.attempt + 1,
            assigned_agent_id=None,
            lease_expires_at=None,
            started_at=None,
            last_error=payload.error,
        )
        event_type = "WORK_ITEM_RETRIED"
    else:
        ok = await update_work_item_status(
            session,
            wi.id,
            ["RUNNING"],
            "FAILED",
            finished_at=now,
            last_error=payload.error,
        )
        event_type = "WORK_ITEM_FAILED"
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unable to fail/retry work item (state changed).")
    wi = await session.get(WorkItem, wi.id)
    async with session.begin():
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type=event_type,
            actor_type="AGENT",
            payload={"work_item_id": str(wi.id), "error": payload.error, "retry": retrying},
        )
        if not retrying:
            await maybe_apply_recovery(session, wi)
            await _maybe_finalize_run(session, wi.run_id)
    await session.refresh(wi)
    return _wi_out(wi)


@router.patch("/projects/{project_id}/stage", response_model=ProjectOut)
@public_router.patch("/projects/{project_id}/stage", response_model=ProjectOut)
async def update_stage(
    project_id: uuid.UUID,
    payload: StageUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    current = project.status.upper()
    target = payload.to_stage.strip().upper()

    if target not in {"INTAKE", "PLAN", "RUN", "EVALUATE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown stage '{target}'")

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid transition {current} -> {target}. Allowed: {sorted(allowed)}",
        )

    # Guards
    if target == "PLAN":
        doc_count = await session.scalar(
            select(func.count()).select_from(
                select(Document.id)
                .where(Document.project_id == project_id, Document.deleted_at.is_(None))
                .subquery()
            )
        ) or 0
        if doc_count == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot move to PLAN: add at least one document (PRD) first.",
            )

    if target == "RUN":
        task_count = await session.scalar(
            select(func.count()).select_from(
                select(Task.id)
                .where(Task.project_id == project_id, Task.deleted_at.is_(None))
                .subquery()
            )
        ) or 0
        if task_count == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot move to RUN: generate tasks first.",
            )

    if target == "EVALUATE":
        completed_runs = await session.scalar(
            select(func.count()).select_from(
                select(Run.id)
                .where(Run.project_id == project_id, Run.status == "COMPLETED")
                .subquery()
            )
        ) or 0
        running_runs = await session.scalar(
            select(func.count()).select_from(
                select(Run.id)
                .where(Run.project_id == project_id, Run.status == "RUNNING")
                .subquery()
            )
        ) or 0
        if completed_runs == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot move to EVALUATE: complete at least one run first.",
            )
        if running_runs > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot move to EVALUATE: a run is still in progress.",
            )

    project.status = target
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return _project_out(project)


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
@public_router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    project_id: uuid.UUID,
    payload: DocumentCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Calculate next version for this project/type
    stmt = (
        select(Document.version)
        .where(Document.project_id == project_id, Document.type == payload.type)
        .order_by(Document.version.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    current_version = result.scalar_one_or_none() or 0
    from hashlib import sha256

    content_hash = sha256(payload.body.encode("utf-8")).hexdigest()

    document = Document(
        project_id=project_id,
        tenant_id=ctx.tenant_id,
        type=payload.type,
        title=payload.title,
        body=payload.body,
        version=current_version + 1,
        content_hash=content_hash,
        source=payload.source,
        created_by=payload.created_by,
    )
    session.add(document)
    await session.flush()
    await log_activity(
        session,
        project_id=project_id,
        entity_type="document",
        entity_id=document.id,
        action_type="document.created",
        metadata={"type": payload.type, "version": document.version},
    )
    await session.commit()
    await session.refresh(document)
    return DocumentOut.model_validate(document)


@router.get("/projects/{project_id}/documents", response_model=List[DocumentOut])
@public_router.get("/projects/{project_id}/documents", response_model=List[DocumentOut])
async def list_documents(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[DocumentOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    result = await session.execute(
        select(Document)
        .where(Document.project_id == project_id, Document.tenant_id == ctx.tenant_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/projects/{project_id}/tasks", response_model=List[TaskOut])
@public_router.get("/projects/{project_id}/tasks", response_model=List[TaskOut])
async def list_tasks(
    project_id: uuid.UUID,
    active_only: bool = Query(default=False),
    latest_per_title: bool = Query(default=False),
    include_deleted: bool = Query(default=False),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[TaskOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    query = select(Task).where(Task.project_id == project_id, Task.tenant_id == ctx.tenant_id)
    if not include_deleted:
        query = query.where(Task.deleted_at.is_(None))
    if active_only:
        query = query.where(Task.status.in_(["PENDING", "RUNNING", "FAILED"]))
    query = query.order_by(Task.updated_at.desc(), Task.created_at.desc())
    result = await session.execute(query)
    tasks = result.scalars().all()
    if latest_per_title:
        seen: set[str] = set()
        deduped: list[Task] = []
        for task in tasks:
            key = " ".join((task.title or "").lower().split())
            if not key:
                key = str(task.id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(task)
        tasks = deduped
    return [_task_out(t) for t in tasks]


@router.get("/projects/{project_id}/improvement-requests", response_model=List[ImprovementRequestOut])
@public_router.get("/projects/{project_id}/improvement-requests", response_model=List[ImprovementRequestOut])
async def list_improvement_requests(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[ImprovementRequestOut]:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(ImprovementRequest)
        .where(ImprovementRequest.project_id == project_id, ImprovementRequest.tenant_id == ctx.tenant_id)
        .order_by(ImprovementRequest.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [_improvement_request_out(row) for row in rows]


@router.get("/projects/{project_id}/requirements/summary", response_model=RequirementSummaryResponse)
@public_router.get("/projects/{project_id}/requirements/summary", response_model=RequirementSummaryResponse)
async def get_requirement_summary(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RequirementSummaryResponse:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    payload = await build_requirement_summary(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return RequirementSummaryResponse.model_validate(payload)


@router.get("/projects/{project_id}/requirements/summary/export")
@public_router.get("/projects/{project_id}/requirements/summary/export")
async def export_requirement_summary(
    project_id: uuid.UUID,
    format: str = Query(default="csv"),
    limit: int = Query(default=5000, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
):
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    payload = await build_requirement_summary(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    fmt = (format or "csv").strip().lower()
    if fmt == "json":
        return JSONResponse(payload)
    if fmt != "csv":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format must be csv or json")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "requirement_id",
            "title",
            "status",
            "priority",
            "health_score",
            "risk_level",
            "stability_score",
            "retry_count",
            "unresolved_count",
            "ai_spend_cents",
            "ai_total_tokens",
            "task_total",
            "task_open",
            "task_in_progress",
            "task_completed",
            "task_failed",
            "run_total",
            "run_running",
            "run_completed",
            "run_failed",
            "improvement_total",
            "improvement_open",
            "improvement_resolved",
            "last_activity_at",
        ]
    )
    for item in payload.get("items", []):
        writer.writerow(
            [
                item.get("requirement_id"),
                item.get("title"),
                item.get("status"),
                item.get("priority"),
                item.get("health_score"),
                item.get("risk_level"),
                item.get("stability_score"),
                item.get("retry_count"),
                item.get("unresolved_count"),
                item.get("ai_spend_cents"),
                item.get("ai_total_tokens"),
                (item.get("task_counts") or {}).get("total"),
                (item.get("task_counts") or {}).get("open"),
                (item.get("task_counts") or {}).get("in_progress"),
                (item.get("task_counts") or {}).get("completed"),
                (item.get("task_counts") or {}).get("failed"),
                (item.get("run_counts") or {}).get("total"),
                (item.get("run_counts") or {}).get("running"),
                (item.get("run_counts") or {}).get("completed"),
                (item.get("run_counts") or {}).get("failed"),
                (item.get("improvement_counts") or {}).get("total"),
                (item.get("improvement_counts") or {}).get("open"),
                (item.get("improvement_counts") or {}).get("resolved"),
                item.get("last_activity_at"),
            ]
        )
    filename = f"requirements-summary-{project_id}.csv"
    return PlainTextResponse(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/requirements/{requirement_id}/timeline", response_model=RequirementTimelineResponse)
@public_router.get("/projects/{project_id}/requirements/{requirement_id}/timeline", response_model=RequirementTimelineResponse)
async def get_requirement_timeline(
    project_id: uuid.UUID,
    requirement_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RequirementTimelineResponse:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    payload = await build_requirement_timeline(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        requirement_id=requirement_id,
        limit=limit,
        offset=offset,
    )
    return RequirementTimelineResponse.model_validate(payload)


@router.get("/projects/{project_id}/requirements/{requirement_id}/execution-graph", response_model=RequirementExecutionGraphOut)
@public_router.get(
    "/projects/{project_id}/requirements/{requirement_id}/execution-graph",
    response_model=RequirementExecutionGraphOut,
)
async def get_requirement_execution_graph(
    project_id: uuid.UUID,
    requirement_id: str,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RequirementExecutionGraphOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    payload = await build_requirement_execution_graph(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        requirement_id=requirement_id,
    )
    return RequirementExecutionGraphOut(
        requirement_id=requirement_id,
        tasks=[_task_out(task) for task in payload["tasks"]],
        runs=[_run_out(run) for run in payload["runs"]],
        improvements=[_improvement_request_out(item) for item in payload["improvements"]],
        artifacts=[
            {
                "id": str(artifact.id),
                "type": artifact.type,
                "uri": artifact.uri,
                "run_id": str(artifact.run_id) if artifact.run_id else None,
                "task_id": str(artifact.task_id) if artifact.task_id else None,
                "created_at": artifact.created_at,
            }
            for artifact in payload["artifacts"]
        ],
        pull_requests=payload["pull_requests"],
        deploys=payload["deploys"],
        related_files=payload["related_files"],
        related_modules=payload["related_modules"],
    )


@router.post("/projects/{project_id}/requirements/{requirement_id}/memory")
@public_router.post("/projects/{project_id}/requirements/{requirement_id}/memory")
async def refresh_requirement_memory(
    project_id: uuid.UUID,
    requirement_id: str,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    memory = await compress_requirement_memory(
        session,
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        requirement_id=requirement_id,
    )
    await session.commit()
    await session.refresh(memory)
    return {
        "id": str(memory.id),
        "requirement_id": memory.requirement_id,
        "compact_summary": memory.compact_summary,
        "historical_patterns": memory.historical_patterns,
        "prior_successful_fixes": memory.prior_successful_fixes,
        "recurring_failures": memory.recurring_failures,
        "architectural_constraints": memory.architectural_constraints,
        "validation_patterns": memory.validation_patterns,
        "updated_at": memory.updated_at,
    }


@router.post("/projects/{project_id}/external-references", response_model=ExternalReferenceOut)
@public_router.post("/projects/{project_id}/external-references", response_model=ExternalReferenceOut)
async def ingest_external_reference(
    project_id: uuid.UUID,
    payload: ExternalReferenceIngestRequest,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ExternalReferenceOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        artifact = await persist_external_reference(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            source_url=payload.url,
            run_id=payload.run_id,
            task_id=payload.task_id,
            work_item_id=payload.work_item_id,
            requirement_id=payload.requirement_id,
            label=payload.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if artifact.run_id:
        await record_event(
            session,
            project_id=project_id,
            run_id=artifact.run_id,
            work_item_id=artifact.work_item_id,
            actor_type="USER",
            actor_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            event_type="EXTERNAL_REFERENCE_INGESTED",
            payload={
                "artifact_id": str(artifact.id),
                "uri": artifact.uri,
                "domain": (artifact.extra_metadata or {}).get("domain"),
                "requirement_id": artifact.requirement_id,
            },
        )
    await session.commit()
    await session.refresh(artifact)
    return _external_reference_out(artifact)


@router.get("/projects/{project_id}/requirements/{requirement_id}/memory")
@public_router.get("/projects/{project_id}/requirements/{requirement_id}/memory")
async def get_requirement_memory(
    project_id: uuid.UUID,
    requirement_id: str,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> dict:
    memory = await session.scalar(
        select(RequirementMemory).where(
            RequirementMemory.project_id == project_id,
            RequirementMemory.tenant_id == ctx.tenant_id,
            RequirementMemory.requirement_id == requirement_id,
        )
    )
    if memory is None:
        memory = await compress_requirement_memory(
            session,
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            requirement_id=requirement_id,
        )
        await session.commit()
        await session.refresh(memory)
    return {
        "id": str(memory.id),
        "requirement_id": memory.requirement_id,
        "compact_summary": memory.compact_summary,
        "historical_patterns": memory.historical_patterns,
        "prior_successful_fixes": memory.prior_successful_fixes,
        "recurring_failures": memory.recurring_failures,
        "architectural_constraints": memory.architectural_constraints,
        "validation_patterns": memory.validation_patterns,
        "updated_at": memory.updated_at,
    }


@router.post(
    "/projects/{project_id}/requirements/relationships",
    response_model=RequirementRelationshipOut,
    status_code=status.HTTP_201_CREATED,
)
@public_router.post(
    "/projects/{project_id}/requirements/relationships",
    response_model=RequirementRelationshipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_requirement_relationship(
    project_id: uuid.UUID,
    payload: RequirementRelationshipCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> RequirementRelationshipOut:
    row = RequirementRelationship(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        from_requirement_id=payload.from_requirement_id.strip(),
        to_requirement_id=payload.to_requirement_id.strip(),
        relation_type=payload.relation_type.strip().lower(),
        rationale=payload.rationale,
        created_by=payload.created_by or ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return RequirementRelationshipOut.model_validate(row)


@router.get("/projects/{project_id}/requirements/{requirement_id}/relationships", response_model=list[RequirementRelationshipOut])
@public_router.get(
    "/projects/{project_id}/requirements/{requirement_id}/relationships",
    response_model=list[RequirementRelationshipOut],
)
async def list_requirement_relationships(
    project_id: uuid.UUID,
    requirement_id: str,
    relation_type: str | None = Query(default=None),
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> list[RequirementRelationshipOut]:
    query = select(RequirementRelationship).where(
        RequirementRelationship.project_id == project_id,
        RequirementRelationship.tenant_id == ctx.tenant_id,
        (RequirementRelationship.from_requirement_id == requirement_id)
        | (RequirementRelationship.to_requirement_id == requirement_id),
    )
    if relation_type:
        query = query.where(RequirementRelationship.relation_type == relation_type.strip().lower())
    rows = (await session.execute(query.order_by(RequirementRelationship.created_at.desc()))).scalars().all()
    return [RequirementRelationshipOut.model_validate(row) for row in rows]


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
@public_router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    project = await session.scalar(_project_scoped(session, ctx, project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    document = None
    if payload.document_id:
        document = await session.scalar(
            select(Document).where(Document.id == payload.document_id, Document.tenant_id == ctx.tenant_id)
        )
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        if document.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document not in project")

    task = Task(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        document_id=payload.document_id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        stage=payload.stage,
        status=payload.status,
        assignee=payload.assignee,
        source=payload.source,
        source_type=payload.source_type,
        source_node_id=payload.source_node_id,
        requirement_id=(payload.requirement_id or (payload.derived_from_requirement_ids[0] if payload.derived_from_requirement_ids else None)),
        derived_from_requirement_ids=payload.derived_from_requirement_ids or None,
        capability_id=payload.capability_id,
        capability_label=payload.capability_label,
        architecture_slice=payload.architecture_slice,
        impact_zone=payload.impact_zone or None,
        provenance=payload.provenance or None,
        created_by=payload.created_by,
        branch_strategy=payload.branch_strategy,
        base_branch=payload.base_branch,
        branch_name=payload.branch_name,
    )
    session.add(task)
    await session.flush()
    if document and (payload.derived_from_requirement_ids or payload.capability_id):
        add_task_lineage_traces(
            session,
            task=task,
            document=document,
            requirement_ids=payload.derived_from_requirement_ids,
            capability_id=payload.capability_id,
            confidence=None,
        )
    await log_activity(
        session,
        project_id=project_id,
        entity_type="task",
        entity_id=task.id,
        action_type="task.created",
        metadata={
            "title": payload.title,
            "status": payload.status,
            "branch_strategy": payload.branch_strategy,
            "base_branch": payload.base_branch,
            "branch_name": payload.branch_name,
            "source_type": payload.source_type,
            "derived_from_requirement_ids": payload.derived_from_requirement_ids,
            "capability_id": payload.capability_id,
        },
    )
    await session.commit()
    await session.refresh(task)
    return _task_out(task)


async def _task_counts(session: AsyncSession, project_id: uuid.UUID) -> TaskCounts:
    """Aggregate task counts by status for summary/metrics."""
    result = await session.execute(
        select(Task.status, func.count())
        .where(Task.project_id == project_id, Task.deleted_at.is_(None))
        .group_by(Task.status)
    )
    counts = {row[0]: row[1] for row in result.all()}
    return TaskCounts(
        pending=counts.get("PENDING", 0),
        running=counts.get("RUNNING", 0),
        done=counts.get("DONE", 0),
        failed=counts.get("FAILED", 0),
        canceled=counts.get("CANCELED", 0),
    )


@router.get("/projects/{project_id}/summary", response_model=ProjectSummaryResponse)
@public_router.get("/projects/{project_id}/summary", response_model=ProjectSummaryResponse)
async def project_summary(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ProjectSummaryResponse:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    legacy_project = await ensure_legacy_project(session, project.id)
    req_plan_state = load_requirements_plan_state(str(project.id))
    graph = req_plan_state["graph"]
    plan_status = req_plan_state["plan_status"]
    task_counts = await _task_counts(session, project_id)
    latest_summary_rows = await ensure_project_run_summaries(
        session,
        tenant_id=project.tenant_id,
        project_id=project.id,
        limit=1,
    )
    latest_run_row = await session.scalar(
        select(Run)
        .where(Run.project_id == project_id, Run.tenant_id == project.tenant_id)
        .order_by(*_run_activity_ordering())
        .limit(1)
    )
    latest_run = None
    architecture_summary = None
    project_contract_summary = None
    if latest_run_row is not None:
        latest_summary = latest_summary_rows[0] if latest_summary_rows else None
        run_summary_meta = latest_run_row.summary if isinstance(latest_run_row.summary, dict) else {}
        delivery_commit_sha = (
            _delivery_summary_value(run_summary_meta, "pull_request_commit_sha")
            or _delivery_summary_value(run_summary_meta, "remote_branch_commit_sha")
        )
        pull_request_number = run_summary_meta.get("pull_request_number") if isinstance(run_summary_meta, dict) else None
        if isinstance(pull_request_number, str) and pull_request_number.isdigit():
            pull_request_number = int(pull_request_number)
        latest_pr_number = latest_summary.pull_request_number if latest_summary is not None else pull_request_number
        latest_run = RunSummary(
            run_id=str(latest_run_row.id),
            status=latest_summary.status if latest_summary is not None else latest_run_row.status,
            stage=project.status,
            started_at=latest_run_row.started_at,
            finished_at=latest_summary.finished_at if latest_summary is not None else latest_run_row.finished_at,
            executor=latest_summary.executor if latest_summary is not None else latest_run_row.executor,
            goal_text=(
                latest_summary.goal_text
                if latest_summary is not None
                else _delivery_summary_value(run_summary_meta, "goal")
                or _delivery_summary_value(run_summary_meta, "title")
            ),
            branch_name=latest_summary.branch_name if latest_summary is not None else latest_run_row.branch_name,
            workspace_status=(
                latest_summary.workspace_status if latest_summary is not None else latest_run_row.workspace_status
            ),
            recovery_count=latest_summary.recovery_count if latest_summary is not None else 0,
            artifact_count=latest_summary.artifact_count if latest_summary is not None else 0,
            files_changed=list(latest_summary.changed_files) if latest_summary is not None else [],
            diff_summary=_delivery_summary_value(run_summary_meta, "diff_summary"),
            primary_error=latest_summary.primary_error if latest_summary is not None else latest_run_row.workspace_error,
            approval_status=latest_summary.approval_status if latest_summary is not None else None,
            pull_request_url=latest_summary.pr_url if latest_summary is not None else _delivery_summary_value(run_summary_meta, "pull_request_url"),
            pull_request_number=latest_pr_number if isinstance(latest_pr_number, int) else None,
            delivery_pushed=bool(run_summary_meta.get("remote_branch_pushed")),
            delivery_branch_name=(
                _delivery_summary_value(run_summary_meta, "remote_branch_name")
                or (latest_summary.branch_name if latest_summary is not None else latest_run_row.branch_name)
            ),
            delivery_commit_sha=delivery_commit_sha,
            delivery_pushed_at=_delivery_summary_value(run_summary_meta, "remote_branch_pushed_at"),
        )
        architecture_summary = await summarize_architecture_profile(
            session,
            tenant_id=project.tenant_id,
            project_id=project.id,
            touched_files=list(latest_summary.changed_files) if latest_summary is not None else [],
        )
        project_contract_summary = await summarize_project_contract(
            session,
            tenant_id=project.tenant_id,
            project_id=project.id,
        )
    else:
        architecture_summary = await summarize_architecture_profile(
            session,
            tenant_id=project.tenant_id,
            project_id=project.id,
        )
        project_contract_summary = await summarize_project_contract(
            session,
            tenant_id=project.tenant_id,
            project_id=project.id,
        )
    return ProjectSummaryResponse(
        project_id=str(project.id),
        name=project.name,
        current_stage=project.status,
        latest_run=latest_run,
        architecture_profile=architecture_summary,
        project_contract=project_contract_summary,
        task_counts=task_counts,
        architecture_refresh_needed=legacy_project.architecture_refresh_needed,
        plan_refresh_needed=legacy_project.plan_refresh_needed,
        test_refresh_needed=legacy_project.test_refresh_needed,
        requirements_status=graph.status.value if graph else None,
        requirements_version=graph.version if graph else None,
        requirements_sha=req_plan_state["requirements_sha"],
        plan_exists=plan_status["exists"],
        plan_fresh=plan_status["fresh"],
        plan_id=plan_status["plan_id"],
        plan_requirements_sha=plan_status["requirements_sha"],
        plan_created_at=plan_status["created_at"],
    )


@router.get("/projects/{project_id}/metrics", response_model=ProjectMetricsResponse)
@public_router.get("/projects/{project_id}/metrics", response_model=ProjectMetricsResponse)
async def project_metrics(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ProjectMetricsResponse:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # With persistence only, we don't yet track runs/changes; return zeros.
    return ProjectMetricsResponse(
        total_runs=0,
        active_runs=0,
        stale_count=0,
        open_changes=0,
    )


@router.get("/projects/{project_id}/plan/history", response_model=PlanHistoryResponse)
@public_router.get("/projects/{project_id}/plan/history", response_model=PlanHistoryResponse)
async def plan_history(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> PlanHistoryResponse:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    await ensure_legacy_project(session, project.id)
    plan_history_entries = load_requirements_plan_state(str(project.id))["plan_history"]
    return PlanHistoryResponse(project_id=str(project.id), entries=plan_history_entries)
