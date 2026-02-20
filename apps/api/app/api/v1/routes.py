from __future__ import annotations

from fastapi import APIRouter, HTTPException, status, Request

from app.api.v1.schemas import (
    AdvanceStageRequest,
    ApprovalResponse,
    AuditLogResponse,
    CreateProjectRequest,
    CreateRunRequest,
    ChangeRequestCreate,
    ChangeRequestDecision,
    ChangeRequestResponse,
    DecideApprovalRequest,
    PRDIngestRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectMetricsResponse,
    RequestApprovalRequest,
    RunResponse,
    RunSummary,
    RunMetricsResponse,
    TaskResponse,
    TaskCounts,
    StatusResponse,
    TransitionResponse,
    TriggerAgentRunRequest,
    RequirementGraphApproveRequest,
    RequirementGraphApproveResponse,
    RequirementGraphModel,
    RequirementGraphUpdateRequest,
    PlanRegenerateRequest,
    PlanRegenerateResponse,
    PlanHistoryResponse,
)
from app.services import (
    approval_service,
    audit_service,
    change_service,
    metrics_service,
    planner_service,
    project_service,
    requirements_service,
    run_service,
    github_adapter,
    documentation_guard,
    github_store,
)
from app.services.vcs.github_store import GitHubIntegration
from app.services.errors import (
    ApprovalNotFoundError,
    ApprovalRequiredError,
    ChangeRequestNotFoundError,
    InvalidRunTransitionError,
    InvalidStageError,
    InvalidTransitionError,
    InvalidChangeStatusError,
    ProjectNotFoundError,
    RunNotFoundError,
    StaleArtifactsError,
    RequirementGraphNotFoundError,
    RequirementGraphNotApprovedError,
    RequirementGraphStaleError,
)
from core.models import TaskStatus
from app.services.requirements_service import graph_to_dict, build_edges, build_nodes

router = APIRouter()
projects_router = APIRouter(prefix="/projects", tags=["projects"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])
agents_router = APIRouter(prefix="/agents", tags=["agents"])
runs_router = APIRouter(prefix="/runs", tags=["runs"])
changes_router = APIRouter(prefix="/changes", tags=["changes"])


def _project_response(project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        current_stage=project.current_stage.value,
        architecture_refresh_needed=project.architecture_refresh_needed,
        plan_refresh_needed=project.plan_refresh_needed,
        test_refresh_needed=project.test_refresh_needed,
        created_at=project.created_at,
    )


def _approval_response(record) -> ApprovalResponse:
    approval = record.approval
    return ApprovalResponse(
        id=approval.id,
        project_id=approval.project_id,
        stage=approval.stage.value,
        status=record.status.value,
        requested_by=approval.requested_by,
        requested_at=approval.requested_at,
        decided_by=record.decided_by,
        decided_at=record.decided_at,
        comment=approval.comment,
    )


def _run_response(run) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        project_id=run.project_id,
        stage=run.stage.value,
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _audit_response(log) -> AuditLogResponse:
    return AuditLogResponse(
        timestamp=log.timestamp,
        run_id=log.run_id,
        stage=log.stage.value,
        agent=log.agent_name,
        tool=log.tool_name,
        message=log.message,
        details=log.details or None,
    )


def _task_response(task) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        run_id=task.run_id,
        agent=task.agent,
        title=task.title,
        status=task.status.value,
        depends_on=list(task.depends_on),
        parallel_group=task.parallel_group,
        outputs=list(task.outputs),
        linked_requirements=list(getattr(task, "linked_requirements", [])),
        plan_id=getattr(task, "plan_id", None),
        plan_version=getattr(task, "plan_version", None),
        parent_task_id=getattr(task, "parent_task_id", None),
        superseded_by=getattr(task, "superseded_by", None),
        deprecated=getattr(task, "deprecated", False),
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
    )


def _task_counts(tasks) -> TaskCounts:
    counts = {
        TaskStatus.PENDING: 0,
        TaskStatus.RUNNING: 0,
        TaskStatus.DONE: 0,
        TaskStatus.FAILED: 0,
        TaskStatus.CANCELED: 0,
    }
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    return TaskCounts(
        pending=counts[TaskStatus.PENDING],
        running=counts[TaskStatus.RUNNING],
        done=counts[TaskStatus.DONE],
        failed=counts[TaskStatus.FAILED],
        canceled=counts[TaskStatus.CANCELED],
    )


def _run_summary(run) -> RunSummary:
    return RunSummary(
        run_id=run.run_id,
        status=run.status.value,
        stage=run.stage.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _change_response(change) -> ChangeRequestResponse:
    return ChangeRequestResponse(
        id=change.id,
        project_id=change.project_id,
        source=change.source.value,
        summary=change.summary,
        affected_area=change.affected_area.value,
        severity=change.severity.value,
        suggested_stage=change.suggested_stage.value,
        status=change.status.value,
        created_at=change.created_at,
        decided_at=change.decided_at,
        decided_by=change.decided_by,
    )


def _render_guard_comment(guard: dict) -> str:
    impacted = guard.get("impacted_requirements") or []
    impacted_lines = "\n".join(f"- {req}" for req in impacted) if impacted else "- None"
    plan_status = "❌ Stale" if guard.get("plan_stale") else "✅ Fresh"
    return (
        "## 🧠 Agentic SDLC Documentation Guard\n\n"
        "Impacted Requirements:\n"
        f"{impacted_lines}\n\n"
        f"Plan Status: {plan_status}\n\n"
        "Action Required:\n"
        "- Regenerate Plan\n"
        "- Confirm documentation alignment\n"
    )


@projects_router.post("", response_model=ProjectResponse)
def create_project(payload: CreateProjectRequest) -> ProjectResponse:
    project = project_service.create_project(payload.name, payload.description)
    return _project_response(project)


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str) -> ProjectResponse:
    try:
        project = project_service.get_project(project_id)
        return _project_response(project)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.post("/{project_id}/advance", response_model=TransitionResponse)
def advance_stage(project_id: str, payload: AdvanceStageRequest) -> TransitionResponse:
    try:
        project, transition = project_service.advance_stage(project_id, payload.to_stage)
        return TransitionResponse(
            project=_project_response(project),
            from_stage=transition.from_stage.value,
            to_stage=transition.to_stage.value,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StaleArtifactsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RequirementGraphNotApprovedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RequirementGraphStaleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@projects_router.post("/{project_id}/approvals", response_model=ApprovalResponse)
def request_approval(
    project_id: str, payload: RequestApprovalRequest
) -> ApprovalResponse:
    try:
        project_service.get_project(project_id)
        record = approval_service.request_approval(
            project_id=project_id,
            stage=payload.stage,
            requested_by=payload.requested_by,
            comment=payload.comment,
        )
        return _approval_response(record)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StaleArtifactsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@projects_router.post("/{project_id}/runs", response_model=RunResponse)
def create_run(project_id: str, payload: CreateRunRequest | None = None) -> RunResponse:
    try:
        project = project_service.get_project(project_id)
        if payload and payload.stage:
            try:
                stage = Stage(payload.stage)
            except ValueError:
                stage = Stage[payload.stage.upper()]
        else:
            stage = project.current_stage
        run = run_service.create_run(project_id=project.id, stage=stage)
        return _run_response(run)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@projects_router.get("/{project_id}/runs", response_model=list[RunResponse])
def list_runs(project_id: str) -> list[RunResponse]:
    try:
        project_service.get_project(project_id)
        runs = run_service.list_runs(project_id)
        return [_run_response(run) for run in runs]
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.get("/{project_id}/artifacts", response_model=StatusResponse)
def fetch_artifacts(project_id: str) -> StatusResponse:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Fetch artifacts not implemented",
    )


@projects_router.get("/{project_id}/summary", response_model=ProjectSummaryResponse)
def get_project_summary(project_id: str) -> ProjectSummaryResponse:
    try:
        project = project_service.get_project(project_id)
        graph = None
        graph_hash = None
        try:
            graph = requirements_service.get_graph(project_id)
            graph_hash = graph.compute_hash()
        except RequirementGraphNotFoundError:
            graph = None
            graph_hash = None

        plan_status = run_service.get_plan_status(project_id, graph_hash)
        runs = run_service.list_runs(project_id)
        latest_run = runs[-1] if runs else None
        if latest_run is None:
            task_counts = TaskCounts(pending=0, running=0, done=0, failed=0, canceled=0)
            return ProjectSummaryResponse(
                project_id=project.id,
                name=project.name,
                current_stage=project.current_stage.value,
                latest_run=None,
                task_counts=task_counts,
                architecture_refresh_needed=project.architecture_refresh_needed,
                plan_refresh_needed=project.plan_refresh_needed,
                test_refresh_needed=project.test_refresh_needed,
                requirements_status=graph.status.value if graph else None,
                requirements_version=graph.version if graph else None,
                requirements_sha=graph_hash,
                plan_exists=plan_status["exists"],
                plan_fresh=plan_status["fresh"],
                plan_id=plan_status["plan_id"],
                plan_requirements_sha=plan_status["requirements_sha"],
                plan_created_at=plan_status["created_at"],
            )
        tasks = run_service.list_tasks(latest_run.run_id)
        return ProjectSummaryResponse(
            project_id=project.id,
            name=project.name,
            current_stage=project.current_stage.value,
            latest_run=_run_summary(latest_run),
            task_counts=_task_counts(tasks),
            architecture_refresh_needed=project.architecture_refresh_needed,
            plan_refresh_needed=project.plan_refresh_needed,
            test_refresh_needed=project.test_refresh_needed,
            requirements_status=graph.status.value if graph else None,
            requirements_version=graph.version if graph else None,
            requirements_sha=graph_hash,
            plan_exists=plan_status["exists"],
            plan_fresh=plan_status["fresh"],
            plan_id=plan_status["plan_id"],
            plan_requirements_sha=plan_status["requirements_sha"],
            plan_created_at=plan_status["created_at"],
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@projects_router.post("/{project_id}/prd", response_model=RequirementGraphModel)
def ingest_prd(project_id: str, payload: PRDIngestRequest) -> RequirementGraphModel:
    try:
        graph = requirements_service.ingest_prd(
            project_id=project_id,
            text=payload.text,
            source=payload.source,
            fmt=payload.format,
        )
        return RequirementGraphModel(**graph_to_dict(graph))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.get("/{project_id}/requirements-graph", response_model=RequirementGraphModel)
def get_requirements_graph(project_id: str) -> RequirementGraphModel:
    try:
        graph = requirements_service.get_graph(project_id)
        return RequirementGraphModel(**graph_to_dict(graph))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RequirementGraphNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.post("/{project_id}/plan/regenerate", response_model=PlanRegenerateResponse)
def regenerate_plan(project_id: str, payload: PlanRegenerateRequest) -> PlanRegenerateResponse:
    try:
        result = planner_service.regenerate_plan(
            project_id,
            triggered_by=payload.triggered_by,
            mode=payload.mode,
        )
        return PlanRegenerateResponse(**result)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RequirementGraphNotApprovedError, RequirementGraphStaleError, StaleArtifactsError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@projects_router.get("/{project_id}/plan/history", response_model=PlanHistoryResponse)
def get_plan_history(project_id: str) -> PlanHistoryResponse:
    try:
        project_service.get_project(project_id)
        entries = planner_service.list_history(project_id)
        return PlanHistoryResponse(project_id=project_id, entries=entries)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.put("/{project_id}/requirements-graph", response_model=RequirementGraphModel)
def update_requirements_graph(
    project_id: str, payload: RequirementGraphUpdateRequest
) -> RequirementGraphModel:
    try:
        nodes = build_nodes([node.model_dump() for node in payload.nodes])
        edges = build_edges([edge.model_dump() for edge in payload.edges])
        graph = requirements_service.update_graph(project_id, nodes, edges)
        return RequirementGraphModel(**graph_to_dict(graph))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RequirementGraphNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.post(
    "/{project_id}/requirements-graph/approve",
    response_model=RequirementGraphApproveResponse,
)
def approve_requirements_graph(
    project_id: str, payload: RequirementGraphApproveRequest
) -> RequirementGraphApproveResponse:
    try:
        snapshot = requirements_service.approve_graph(
            project_id=project_id, approved_by=payload.approved_by
        )
        graph = requirements_service.get_graph(project_id)
        return RequirementGraphApproveResponse(
            project_id=project_id,
            version=graph.version,
            sha256=snapshot.sha256,
            status=graph.status.value,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RequirementGraphNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.get("/{project_id}/metrics", response_model=ProjectMetricsResponse)
def get_project_metrics(project_id: str) -> ProjectMetricsResponse:
    try:
        project_service.get_project(project_id)
        data = metrics_service.get_project_metrics(project_id)
        return ProjectMetricsResponse(**data)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.post("/{project_id}/changes", response_model=ChangeRequestResponse)
def create_change_request(project_id: str, payload: ChangeRequestCreate) -> ChangeRequestResponse:
    try:
        project_service.get_project(project_id)
        change = change_service.create(
            project_id=project_id,
            source=payload.source,
            summary=payload.summary,
            affected_area=payload.affected_area,
            severity=payload.severity,
            suggested_stage=payload.suggested_stage,
        )
        return _change_response(change)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@projects_router.get("/{project_id}/changes", response_model=list[ChangeRequestResponse])
def list_change_requests(project_id: str) -> list[ChangeRequestResponse]:
    try:
        project_service.get_project(project_id)
        changes = change_service.list_for_project(project_id)
        return [_change_response(change) for change in changes]
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@projects_router.get("/{project_id}/audit-logs", response_model=list[AuditLogResponse])
def fetch_audit_logs(project_id: str) -> list[AuditLogResponse]:
    try:
        project_service.get_project(project_id)
        logs = audit_service.get_project_audit_logs(project_id)
        return [_audit_response(log) for log in logs]
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@approvals_router.post("/{approval_id}/decision", response_model=ApprovalResponse)
def decide_approval(
    approval_id: str, payload: DecideApprovalRequest
) -> ApprovalResponse:
    try:
        record = approval_service.decide(
            approval_id=approval_id,
            decision=payload.decision,
            decided_by=payload.decided_by,
            comment=payload.comment,
        )
        return _approval_response(record)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@agents_router.post("/runs", response_model=StatusResponse)
def trigger_agent_run(payload: TriggerAgentRunRequest) -> StatusResponse:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Trigger agent run not implemented",
    )


@runs_router.post("/{run_id}/start", response_model=RunResponse)
def start_run(run_id: str) -> RunResponse:
    try:
        run = run_service.start_run(run_id)
        return _run_response(run)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StaleArtifactsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@runs_router.post("/{run_id}/pause", response_model=RunResponse)
def pause_run(run_id: str) -> RunResponse:
    try:
        run = run_service.pause_run(run_id)
        return _run_response(run)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@runs_router.post("/{run_id}/resume", response_model=RunResponse)
def resume_run(run_id: str) -> RunResponse:
    try:
        run = run_service.resume_run(run_id)
        return _run_response(run)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@runs_router.post("/{run_id}/complete", response_model=RunResponse)
def complete_run(run_id: str) -> RunResponse:
    try:
        run = run_service.complete_run(run_id)
        return _run_response(run)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@runs_router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: str) -> RunResponse:
    try:
        run = run_service.cancel_run(run_id)
        return _run_response(run)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidRunTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@runs_router.get("/{run_id}/tasks", response_model=list[TaskResponse])
def list_tasks(run_id: str) -> list[TaskResponse]:
    try:
        tasks = run_service.list_tasks(run_id)
        return [_task_response(task) for task in tasks]
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@runs_router.post("/{run_id}/execute", response_model=StatusResponse)
def execute_tasks(run_id: str, max_parallel_tasks: int = 2) -> StatusResponse:
    try:
        run_service.execute_tasks_bounded(run_id, max_parallel_tasks=max_parallel_tasks)
        return StatusResponse(status="ok", message="Task execution completed")
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@runs_router.get("/{run_id}/metrics", response_model=RunMetricsResponse)
def get_run_metrics(run_id: str) -> RunMetricsResponse:
    try:
        data = metrics_service.get_run_metrics(run_id)
        return RunMetricsResponse(**data)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@changes_router.post("/{change_id}/accept", response_model=ChangeRequestResponse)
def accept_change(change_id: str, payload: ChangeRequestDecision) -> ChangeRequestResponse:
    try:
        change = change_service.accept(change_id, decided_by=payload.decided_by)
        return _change_response(change)
    except ChangeRequestNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidChangeStatusError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@changes_router.post("/{change_id}/reject", response_model=ChangeRequestResponse)
def reject_change(change_id: str, payload: ChangeRequestDecision) -> ChangeRequestResponse:
    try:
        change = change_service.reject(change_id, decided_by=payload.decided_by)
        return _change_response(change)
    except ChangeRequestNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidChangeStatusError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/webhooks/github")
async def github_webhook(request: Request) -> dict:
    if github_adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub integration not configured",
        )

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not github_adapter.verify_signature(body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event")
    if event != "pull_request":
        return {"status": "ignored", "reason": "event_not_supported"}

    payload = await request.json()
    action = payload.get("action")
    if action not in {"opened", "synchronize", "reopened"}:
        return {"status": "ignored", "reason": f"action_{action}"}

    repo = payload.get("repository", {}).get("full_name")
    org_login = (
        payload.get("organization", {}) or payload.get("repository", {}).get("owner", {}) or {}
    ).get("login")
    installation_id = payload.get("installation", {}).get("id")
    pr_number = payload.get("pull_request", {}).get("number")

    try:
        github_adapter.assert_org_allowed(org_login or "")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    try:
        files = github_adapter.get_pr_files(repo, pr_number, installation_id=installation_id)
    except Exception as exc:  # pragma: no cover - network failure handling
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    guard = documentation_guard.evaluate_guard(repo, pr_number, files)

    # store integration for reuse
    if installation_id and org_login:
        github_store.save(
            GitHubIntegration(
                installation_id=installation_id, org_login=org_login, allowed_repos=[repo] if repo else []
            )
        )

    # optional PR comment
    try:
        comment_body = _render_guard_comment(guard)
        github_adapter.post_pr_comment(repo, pr_number, comment_body, installation_id=installation_id)
    except Exception:
        # best-effort; ignore comment failures
        pass

    return {"status": "ok", "action": action, "guard_status": guard.get("status")}


router.include_router(projects_router)
router.include_router(approvals_router)
router.include_router(agents_router)
router.include_router(runs_router)
router.include_router(changes_router)
