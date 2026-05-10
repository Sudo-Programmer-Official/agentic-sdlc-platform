from __future__ import annotations

import base64
import binascii
import csv
import io
import uuid
from datetime import datetime, timezone
from datetime import timedelta
from types import SimpleNamespace
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, and_, exists, case
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
    ImprovementRequest,
    RequirementMemory,
    RequirementRelationship,
    ProjectBlueprint,
    ProjectGenesisRun,
    ProjectTopologySnapshot,
    StackPreset,
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
from app.services.workspace_supervisor import ensure_run_workspace
from app.services.work_item_state import is_dependency_satisfied
from app.services.requirements_bridge import ensure_legacy_project, load_requirements_plan_state
from app.services.run_summary_builder import ensure_project_run_summaries
from app.services.architecture_profile_service import bootstrap_architecture_profile, summarize_architecture_profile
from app.services.requirement_tracking import build_requirement_summary, build_requirement_timeline
from app.services.requirement_execution_graph import build_requirement_execution_graph
from app.services.requirement_memory import compress_requirement_memory
from app.services.project_contract_service import summarize_project_contract
from app.services.governance_kpis import build_governance_kpis
from app.services.impact_analysis_loop import score_impact_prediction
from app.services.external_reference_ingestion import persist_external_reference
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


# Legacy store prefix (DB-backed) and public projects prefix to align with UI.
router = APIRouter(prefix="/store", tags=["store"])
public_router = APIRouter(tags=["projects"])
settings = get_settings()


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


def _project_scoped(session: AsyncSession, ctx, project_id: uuid.UUID):
    return select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id)


def _run_scoped(session: AsyncSession, ctx, run_id: uuid.UUID):
    return select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id)


def _wi_scoped(session: AsyncSession, ctx, wi_id: uuid.UUID):
    return select(WorkItem).where(WorkItem.id == wi_id, WorkItem.tenant_id == ctx.tenant_id)


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
    async with session.begin():
        project = Project(name=payload.name, description=payload.description, tenant_id=ctx.tenant_id)
        session.add(project)
        await session.flush()
        await log_activity(
            session,
            project_id=project.id,
            entity_type="project",
            entity_id=project.id,
            action_type="project.created",
            metadata={"name": payload.name},
        )
    await session.refresh(project)
    return _project_out(project)


@router.get("/projects", response_model=List[ProjectOut])
@public_router.get("/projects", response_model=List[ProjectOut])
async def list_projects(
    ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)
) -> List[ProjectOut]:
    result = await session.execute(
        select(Project).where(Project.tenant_id == ctx.tenant_id).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return [_project_out(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
@public_router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
        select(Project).where(Project.id == payload.project_id, Project.tenant_id == ctx.tenant_id)
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

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
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    executor_name = (payload.executor if payload else "codex").lower()
    task_id = payload.task_id if payload else None
    try:
        run = await launch_run_for_project(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            executor_name=executor_name,
            task_id=task_id,
            actor_type="USER",
            run_kind=payload.run_kind if payload else None,
            schedule=True,
        )
        return _run_out(run)
    except ValueError as exc:
        detail = str(exc)
        if detail in {"Project not found", "Task not found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


@router.get("/projects/{project_id}/stack-presets", response_model=List[StackPresetOut])
@public_router.get("/projects/{project_id}/stack-presets", response_model=List[StackPresetOut])
async def list_project_stack_presets(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[StackPresetOut]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[RunOut]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(
        select(Run)
        .where(Run.project_id == project_id, Run.tenant_id == ctx.tenant_id)
        .order_by(*_run_activity_ordering())
    )
    runs = result.scalars().all()
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return FoundationReadinessOut(
        **await build_foundation_readiness(session, tenant_id=ctx.tenant_id, project_id=project_id)
    )


@router.get("/projects/{project_id}/governance-kpis", response_model=GovernanceKpisOut)
@public_router.get("/projects/{project_id}/governance-kpis", response_model=GovernanceKpisOut)
async def get_governance_kpis(
    project_id: uuid.UUID,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> GovernanceKpisOut:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    profile = await get_project_preview_profile(session, tenant_id=ctx.tenant_id, project_id=project_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project preview profile not configured")
    return _project_preview_profile_out(profile)


class RunStatusUpdate(BaseModel):
    status: str


class RunForkRequest(BaseModel):
    executor: str | None = None
    branch_name: str | None = None
    start_now: bool = True
    summary_overrides: dict = Field(default_factory=dict)


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
    source_run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
    if not source_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    forked = await fork_run(
        session,
        source_run=source_run,
        executor=payload.executor,
        branch_name=payload.branch_name,
        summary_overrides=payload.summary_overrides,
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
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
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
        select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id).with_for_update(skip_locked=True)
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
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
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

    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
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


@router.post("/runs/{run_id}/create-pr", response_model=PullRequestOut)
@public_router.post("/runs/{run_id}/create-pr", response_model=PullRequestOut)
async def create_run_pull_request(
    run_id: uuid.UUID,
    payload: PullRequestCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> PullRequestOut:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
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
        return PullRequestOut.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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


@router.get("/runs/{run_id}/events", response_model=List[RunEventOut])
@public_router.get("/runs/{run_id}/events", response_model=List[RunEventOut])
async def list_run_events(run_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)) -> List[RunEventOut]:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
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
