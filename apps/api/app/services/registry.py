from core.execution import AgentRegistry
from core.ledger import ActionLedger, InMemoryActionLogStore
from core.sdlc import ApprovalGate, InMemoryStateStore

from agent.runtime import BedrockAgentAdapter, PlannerAgent, RequirementsAgent
from agent.runtime.requirements_intelligence import extract_graph_from_prd
from app.services.vcs import InMemoryGitHubIntegrationStore, build_github_adapter, provider_registry
from app.services.documentation_guard import DocumentationGuardService

from .approval_service import ApprovalService
from .audit_service import AuditService
from .artifact_service import ArtifactSnapshotService, InMemoryArtifactSnapshotStore, InMemoryStaleStageStore
from .change_service import ChangeRequestService, InMemoryChangeStore
from .metrics_service import MetricsService
from .project_service import InMemoryProjectStore, ProjectService
from .planner_service import PlannerService
from .requirements_service import InMemoryRequirementGraphStore, RequirementGraphService
from .run_service import InMemoryRunStore, RunService
from .task_service import InMemoryTaskStore, TaskService

_state_store = InMemoryStateStore()
_project_store = InMemoryProjectStore()
_approval_gate = ApprovalGate()
_run_store = InMemoryRunStore()
_task_store = InMemoryTaskStore()
_action_log_store = InMemoryActionLogStore()
_action_ledger = ActionLedger(_action_log_store)
_artifact_snapshot_store = InMemoryArtifactSnapshotStore()
_stale_stage_store = InMemoryStaleStageStore()
_change_store = InMemoryChangeStore()
_bedrock_adapter = BedrockAgentAdapter()
_requirements_agent = RequirementsAgent(_bedrock_adapter, _action_ledger)
_planner_agent = PlannerAgent(_bedrock_adapter, _action_ledger)
_agent_registry = AgentRegistry()
_agent_registry.register(_requirements_agent)
_agent_registry.register(_planner_agent)
_artifact_service = ArtifactSnapshotService(
    _artifact_snapshot_store,
    _stale_stage_store,
    _action_ledger,
)
_task_service = TaskService(_task_store)

project_service = ProjectService(
    project_store=_project_store,
    state_store=_state_store,
    approval_gate=_approval_gate,
    artifact_service=_artifact_service,
    requirements_service=None,
    plan_checker=None,
)
approval_service = ApprovalService(_approval_gate, _artifact_service)
_requirements_store = InMemoryRequirementGraphStore()
_requirements_service = RequirementGraphService(
    _requirements_store,
    _action_ledger,
    project_service.get_project,
    project_service.set_refresh_flags,
    extractor=extract_graph_from_prd,
    docs_root=_artifact_service._docs_root if hasattr(_artifact_service, "_docs_root") else None,
)
# attach after construction to avoid circular init
project_service._requirements_service = _requirements_service
project_service._plan_checker = lambda pid, gh: run_service.is_plan_fresh(pid, gh)
planner_service = PlannerService(
    planner_agent=_planner_agent,
    ledger=_action_ledger,
    project_getter=project_service.get_project,
    requirements_service=_requirements_service,
    docs_root=_artifact_service._docs_root if hasattr(_artifact_service, "_docs_root") else None,
)
run_service = RunService(
    _run_store,
    _action_ledger,
    agent_registry=_agent_registry,
    project_getter=project_service.get_project,
    artifact_service=_artifact_service,
    task_service=_task_service,
    requirements_service=_requirements_service,
)
project_service._plan_checker = lambda pid, gh: run_service.is_plan_fresh(pid, gh)
audit_service = AuditService(_action_ledger)
change_service = ChangeRequestService(
    _change_store,
    _action_ledger,
    _artifact_service,
    project_service.get_project,
    project_service.set_stage,
)
metrics_service = MetricsService(
    run_service=run_service,
    artifact_service=_artifact_service,
    change_service=change_service,
)

requirements_service = _requirements_service

# GitHub integration
_github_store = InMemoryGitHubIntegrationStore()
github_adapter = build_github_adapter(_github_store)
provider_registry.register(
    "github",
    adapter=github_adapter,
    installation_id_getter=lambda: (
        integration.installation_id if (integration := _github_store.get()) else None
    ),
)
documentation_guard = DocumentationGuardService(
    ledger=_action_ledger,
    docs_root=_artifact_service._docs_root if hasattr(_artifact_service, "_docs_root") else None,
)
github_store = _github_store
