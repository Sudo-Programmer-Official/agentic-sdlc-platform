from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionNodeSpec:
    id: str
    label: str
    lane: str
    current_state: str
    current_work_item_types: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class ExecutionEdgeSpec:
    source: str
    target: str


@dataclass(frozen=True)
class SkipRuleSpec:
    id: str
    description: str
    applies_when: str
    skip_nodes: tuple[str, ...]


@dataclass(frozen=True)
class RetryRuleSpec:
    node_id: str
    max_retries: int
    recovery_action: str
    notes: str


@dataclass(frozen=True)
class ExecutionGraphSpec:
    nodes: tuple[ExecutionNodeSpec, ...]
    edges: tuple[ExecutionEdgeSpec, ...]
    skip_rules: tuple[SkipRuleSpec, ...]
    retry_rules: tuple[RetryRuleSpec, ...]


NODES: tuple[ExecutionNodeSpec, ...] = (
    ExecutionNodeSpec(
        id="PLAN",
        label="Plan",
        lane="planning",
        current_state="implemented",
        current_work_item_types=("PLAN_DAG",),
        description="Capture the bounded run plan and task decomposition before any code changes begin.",
    ),
    ExecutionNodeSpec(
        id="PATCH_VERIFY",
        label="Patch Verify",
        lane="planning",
        current_state="approximated",
        current_work_item_types=("REVIEW_DIFF",),
        description="Advisory verification pass over planned scope, dependent files, and risk before patching.",
    ),
    ExecutionNodeSpec(
        id="APPLY_PATCH",
        label="Apply Patch",
        lane="mutating",
        current_state="implemented",
        current_work_item_types=("CODE_BACKEND", "CODE_FRONTEND"),
        description="The single mutating lane. Backend and frontend patch steps must serialize through one run workspace.",
    ),
    ExecutionNodeSpec(
        id="RUN_LINT",
        label="Run Lint",
        lane="verification",
        current_state="planned",
        current_work_item_types=(),
        description="Static lint and style validation for the changed surface.",
    ),
    ExecutionNodeSpec(
        id="RUN_UNIT_TESTS",
        label="Run Unit Tests",
        lane="verification",
        current_state="implemented",
        current_work_item_types=("WRITE_TESTS", "RUN_TESTS", "FIX_TEST_FAILURE"),
        description="Execute the relevant validation path and bounded recovery loop for test failures.",
    ),
    ExecutionNodeSpec(
        id="BUILD_FRONTEND",
        label="Build Frontend",
        lane="verification",
        current_state="planned",
        current_work_item_types=(),
        description="Build the frontend surface when frontend code changed.",
    ),
    ExecutionNodeSpec(
        id="BUILD_BACKEND",
        label="Build Backend",
        lane="verification",
        current_state="planned",
        current_work_item_types=(),
        description="Build the backend surface when backend code changed.",
    ),
    ExecutionNodeSpec(
        id="VALIDATE_RESULTS",
        label="Validate Results",
        lane="verification",
        current_state="approximated",
        current_work_item_types=("REVIEW_INTEGRATION",),
        description="Join verification outputs into one reviewable validation state before preview or PR.",
    ),
    ExecutionNodeSpec(
        id="CREATE_FRONTEND_PREVIEW",
        label="Create Frontend Preview",
        lane="provisioning",
        current_state="planned",
        current_work_item_types=(),
        description="Provision a frontend preview only when the run changed frontend code and validation passed.",
    ),
    ExecutionNodeSpec(
        id="CREATE_BACKEND_PREVIEW",
        label="Create Backend Preview",
        lane="provisioning",
        current_state="planned",
        current_work_item_types=(),
        description="Provision a backend preview only when the run changed backend code and validation passed.",
    ),
    ExecutionNodeSpec(
        id="SMOKE_TEST_PREVIEW",
        label="Smoke Test Preview",
        lane="provisioning",
        current_state="planned",
        current_work_item_types=(),
        description="Perform a lightweight health check against preview surfaces before human review.",
    ),
    ExecutionNodeSpec(
        id="APPROVAL",
        label="Approval",
        lane="governance",
        current_state="implemented_control_plane",
        current_work_item_types=(),
        description="Human review and approval gate driven by approvals and Mission Control surfaces.",
    ),
    ExecutionNodeSpec(
        id="CREATE_PR",
        label="Create PR",
        lane="governance",
        current_state="implemented_control_plane",
        current_work_item_types=(),
        description="Create the pull request only after approval and successful verification.",
    ),
)


EDGES: tuple[ExecutionEdgeSpec, ...] = (
    ExecutionEdgeSpec("PLAN", "PATCH_VERIFY"),
    ExecutionEdgeSpec("PATCH_VERIFY", "APPLY_PATCH"),
    ExecutionEdgeSpec("APPLY_PATCH", "RUN_LINT"),
    ExecutionEdgeSpec("APPLY_PATCH", "RUN_UNIT_TESTS"),
    ExecutionEdgeSpec("APPLY_PATCH", "BUILD_FRONTEND"),
    ExecutionEdgeSpec("APPLY_PATCH", "BUILD_BACKEND"),
    ExecutionEdgeSpec("RUN_LINT", "VALIDATE_RESULTS"),
    ExecutionEdgeSpec("RUN_UNIT_TESTS", "VALIDATE_RESULTS"),
    ExecutionEdgeSpec("BUILD_FRONTEND", "VALIDATE_RESULTS"),
    ExecutionEdgeSpec("BUILD_BACKEND", "VALIDATE_RESULTS"),
    ExecutionEdgeSpec("VALIDATE_RESULTS", "CREATE_FRONTEND_PREVIEW"),
    ExecutionEdgeSpec("VALIDATE_RESULTS", "CREATE_BACKEND_PREVIEW"),
    ExecutionEdgeSpec("CREATE_FRONTEND_PREVIEW", "SMOKE_TEST_PREVIEW"),
    ExecutionEdgeSpec("CREATE_BACKEND_PREVIEW", "SMOKE_TEST_PREVIEW"),
    ExecutionEdgeSpec("VALIDATE_RESULTS", "APPROVAL"),
    ExecutionEdgeSpec("SMOKE_TEST_PREVIEW", "APPROVAL"),
    ExecutionEdgeSpec("APPROVAL", "CREATE_PR"),
)


SKIP_RULES: tuple[SkipRuleSpec, ...] = (
    SkipRuleSpec(
        id="frontend_only_change",
        description="Skip backend-only verification and provisioning when the scoped patch is frontend-only.",
        applies_when="planned/actual changed files stay inside frontend paths",
        skip_nodes=("BUILD_BACKEND", "CREATE_BACKEND_PREVIEW"),
    ),
    SkipRuleSpec(
        id="backend_only_change",
        description="Skip frontend-only verification and provisioning when the scoped patch is backend-only.",
        applies_when="planned/actual changed files stay inside backend paths",
        skip_nodes=("BUILD_FRONTEND", "CREATE_FRONTEND_PREVIEW"),
    ),
    SkipRuleSpec(
        id="docs_or_config_only_change",
        description="Skip preview provisioning when the run only changes docs or low-risk config.",
        applies_when="planned/actual changed files stay inside docs/config-only envelope",
        skip_nodes=("CREATE_FRONTEND_PREVIEW", "CREATE_BACKEND_PREVIEW", "SMOKE_TEST_PREVIEW"),
    ),
    SkipRuleSpec(
        id="no_preview_profile",
        description="Skip preview nodes when the project does not define a preview profile.",
        applies_when="project preview policy is missing or disabled",
        skip_nodes=("CREATE_FRONTEND_PREVIEW", "CREATE_BACKEND_PREVIEW", "SMOKE_TEST_PREVIEW"),
    ),
)


RETRY_RULES: tuple[RetryRuleSpec, ...] = (
    RetryRuleSpec(
        node_id="PLAN",
        max_retries=0,
        recovery_action="manual_or_requeue_run",
        notes="Planning should be deterministic; repeated planner retries widen variance.",
    ),
    RetryRuleSpec(
        node_id="PATCH_VERIFY",
        max_retries=0,
        recovery_action="require_confirmation_or_reduce_scope",
        notes="Verification should not auto-loop into uncontrolled scope expansion.",
    ),
    RetryRuleSpec(
        node_id="APPLY_PATCH",
        max_retries=0,
        recovery_action="retry_only_through_bounded_recovery_nodes",
        notes="The mutating lane stays single-threaded and should not broad-retry by default.",
    ),
    RetryRuleSpec(
        node_id="RUN_LINT",
        max_retries=1,
        recovery_action="retry_transient_once",
        notes="Lint/build tool flakiness may justify one bounded retry.",
    ),
    RetryRuleSpec(
        node_id="RUN_UNIT_TESTS",
        max_retries=2,
        recovery_action="spawn_fix_test_failure_then_rerun",
        notes="Matches the current RUN_TESTS -> FIX_TEST_FAILURE -> RUN_TESTS recovery slice.",
    ),
    RetryRuleSpec(
        node_id="BUILD_FRONTEND",
        max_retries=1,
        recovery_action="retry_transient_once",
        notes="Build steps get one bounded retry before escalation.",
    ),
    RetryRuleSpec(
        node_id="BUILD_BACKEND",
        max_retries=1,
        recovery_action="retry_transient_once",
        notes="Build steps get one bounded retry before escalation.",
    ),
    RetryRuleSpec(
        node_id="VALIDATE_RESULTS",
        max_retries=0,
        recovery_action="stop_and_surface_verification_state",
        notes="Validation join should not mutate or retrigger broad retries by itself.",
    ),
    RetryRuleSpec(
        node_id="CREATE_FRONTEND_PREVIEW",
        max_retries=1,
        recovery_action="retry_preview_launch_once",
        notes="Preview provisioning can retry once for transient infrastructure issues.",
    ),
    RetryRuleSpec(
        node_id="CREATE_BACKEND_PREVIEW",
        max_retries=1,
        recovery_action="retry_preview_launch_once",
        notes="Preview provisioning can retry once for transient infrastructure issues.",
    ),
    RetryRuleSpec(
        node_id="SMOKE_TEST_PREVIEW",
        max_retries=1,
        recovery_action="retry_preview_health_once",
        notes="Preview smoke tests may retry once before escalation.",
    ),
    RetryRuleSpec(
        node_id="APPROVAL",
        max_retries=0,
        recovery_action="await_human_decision",
        notes="Approval is a human gate, not an automated retry path.",
    ),
    RetryRuleSpec(
        node_id="CREATE_PR",
        max_retries=0,
        recovery_action="manual_retry_after_review",
        notes="PR creation should be explicit and never loop automatically.",
    ),
)


def get_execution_graph_spec() -> ExecutionGraphSpec:
    return ExecutionGraphSpec(
        nodes=NODES,
        edges=EDGES,
        skip_rules=SKIP_RULES,
        retry_rules=RETRY_RULES,
    )


def current_work_item_stage_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for node in NODES:
        for work_item_type in node.current_work_item_types:
            mapping[work_item_type] = node.id
    return mapping
