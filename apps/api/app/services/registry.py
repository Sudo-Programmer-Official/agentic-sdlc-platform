from core.execution import AgentRegistry
from core.ledger import ActionLedger, InMemoryActionLogStore
from core.sdlc import ApprovalGate, InMemoryStateStore

from agent.runtime import BedrockAgentAdapter, PlannerAgent, RequirementsAgent

from .approval_service import ApprovalService
from .audit_service import AuditService
from .artifact_service import ArtifactSnapshotService, InMemoryArtifactSnapshotStore, InMemoryStaleStageStore
from .change_service import ChangeRequestService, InMemoryChangeStore
from .metrics_service import MetricsService
from .project_service import InMemoryProjectStore, ProjectService
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
)
approval_service = ApprovalService(_approval_gate, _artifact_service)
run_service = RunService(
    _run_store,
    _action_ledger,
    agent_registry=_agent_registry,
    project_getter=project_service.get_project,
    artifact_service=_artifact_service,
    task_service=_task_service,
)
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
