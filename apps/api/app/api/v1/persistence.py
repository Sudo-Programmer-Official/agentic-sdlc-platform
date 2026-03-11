from __future__ import annotations

import uuid
from datetime import datetime
from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.db.models import (
    Project,
    Document,
    Task,
    Run,
    RunEvent,
    WorkItem,
    WorkItemEdge,
    Agent,
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
    WorkItemOut,
    WorkItemEdgeOut,
    AgentCreate,
    AgentOut,
    WorkItemComplete,
    WorkItemFail,
)
from app.services.activity_log import log_activity
from app.services.event_log import record_event
from app.services.runtime_lineage import persist_work_item_artifacts
from app.services.state_guard import update_run_status, update_work_item_status
from app.runtime.orchestrator import RunOrchestrator
from app.db.session import SessionLocal
from app.api.v1.schemas import (
    ProjectSummaryResponse,
    TaskCounts,
    ProjectMetricsResponse,
    PlanHistoryResponse,
)
from app.core.config import get_settings
from app.api.deps import get_tenant_context, get_tenant_id, ZERO_TENANT


# Legacy store prefix (DB-backed) and public projects prefix to align with UI.
router = APIRouter(prefix="/store", tags=["store"])
public_router = APIRouter(tags=["projects"])
settings = get_settings()


class StageUpdate(BaseModel):
    to_stage: str


ALLOWED_TRANSITIONS = {
    "INTAKE": {"PLAN"},
    "PLAN": {"RUN"},
    "RUN": {"EVALUATE"},
    "EVALUATE": set(),
}

RUN_ALLOWED = {
    "QUEUED": {"RUNNING"},
    "RUNNING": {"COMPLETED", "FAILED", "CANCELED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELED": set(),
}


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


def _wi_out(wi: WorkItem) -> WorkItemOut:
    return WorkItemOut.model_validate(wi)


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
    counts = (
        await session.execute(
            select(
                func.count().filter(WorkItem.status == "FAILED"),
                func.count().filter(WorkItem.status.in_(["RUNNING", "CLAIMED"])),
                func.count().filter(WorkItem.status == "QUEUED"),
            ).where(WorkItem.run_id == run_id)
        )
    ).first()
    failed, active, queued = counts
    if failed and active == 0 and queued == 0:
        run.status = "FAILED"
        run.finished_at = datetime.utcnow()
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
        run.finished_at = datetime.utcnow()
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_COMPLETED",
            actor_type="SYSTEM",
        )
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


@router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    project_id: uuid.UUID,
    payload: RunCreate | None = None,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    existing_running = await session.scalar(
        select(func.count()).select_from(
            select(Run.id)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id, Run.status == "RUNNING")
            .subquery()
        )
    ) or 0
    if existing_running > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already in progress for this project; finish or cancel it before starting another.",
        )
    executor_name = (payload.executor if payload else "dummy").lower()
    async with session.begin():
        run = Run(project_id=project_id, tenant_id=tenant_id, status="QUEUED")
        run.executor = executor_name
        session.add(run)
        await session.flush()
        await log_activity(
            session,
            project_id=project_id,
            entity_type="run",
            entity_id=run.id,
            action_type="run.created",
            metadata={"status": run.status},
        )
        await record_event(
            session,
            project_id=project_id,
            run_id=run.id,
            event_type="RUN_CREATED",
            actor_type="USER",
        )
    await session.refresh(run)
    # Kick off orchestrator asynchronously
    orchestrator = RunOrchestrator(SessionLocal, executor_name=executor_name)
    asyncio.create_task(orchestrator.start(run.id, actor_type="USER", executor_name=executor_name))
    return _run_out(run)


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
        select(Run).where(Run.project_id == project_id, Run.tenant_id == ctx.tenant_id).order_by(Run.created_at.desc())
    )
    runs = result.scalars().all()
    return [_run_out(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)) -> RunOut:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == ctx.tenant_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _run_out(run)


class RunStatusUpdate(BaseModel):
    status: str


class RunEventOut(BaseModel):
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
    lease_seconds: int = 60


@router.patch("/runs/{run_id}/status", response_model=RunOut)
async def update_run_status(
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
    ok = await update_run_status(session, run_id, ["QUEUED", "RUNNING"], "CANCELED")
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run already finished or locked.")
    async with session.begin():
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
    await session.refresh(run)
    return _run_out(run)


@router.get("/runs/{run_id}/events", response_model=List[RunEventOut])
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
    agent.last_heartbeat_at = datetime.utcnow()
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
    now = datetime.utcnow()
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
        .where(
            WorkItem.status == "QUEUED",
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
    now = datetime.utcnow()
    if wi.lease_expires_at and wi.lease_expires_at < now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lease expired; please re-claim the work item.")
    ok = await update_work_item_status(
        session,
        wi.id,
        ["RUNNING"],
        "DONE",
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
            event_type="WORK_ITEM_DONE",
            actor_type="AGENT",
            payload={"work_item_id": str(wi.id), "status": "DONE"},
        )
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
    now = datetime.utcnow()
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
    async with session.begin():
        session.add(project)
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

    async with session.begin():
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
    project_id: uuid.UUID, ctx=Depends(get_tenant_context), session: AsyncSession = Depends(get_session)
) -> List[TaskOut]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(select(Task).where(Task.project_id == project_id, Task.tenant_id == ctx.tenant_id))
    tasks = result.scalars().all()
    return [TaskOut.model_validate(t) for t in tasks]


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

    if payload.document_id:
        document = await session.scalar(
            select(Document).where(Document.id == payload.document_id, Document.tenant_id == ctx.tenant_id)
        )
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        if document.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document not in project")

    async with session.begin():
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
            created_by=payload.created_by,
        )
        session.add(task)
        await session.flush()
        await log_activity(
            session,
            project_id=project_id,
            entity_type="task",
            entity_id=task.id,
            action_type="task.created",
            metadata={"title": payload.title, "status": payload.status},
        )
    await session.refresh(task)
    return TaskOut.model_validate(task)


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

    task_counts = await _task_counts(session, project_id)
    # No plan/requirements/run data in persistence layer yet; return safe defaults.
    return ProjectSummaryResponse(
        project_id=str(project.id),
        name=project.name,
        current_stage=project.status,
        latest_run=None,
        task_counts=task_counts,
        architecture_refresh_needed=getattr(project, "architecture_refresh_needed", False),
        plan_refresh_needed=getattr(project, "plan_refresh_needed", False),
        test_refresh_needed=getattr(project, "test_refresh_needed", False),
        requirements_status=None,
        requirements_version=None,
        requirements_sha=None,
        plan_exists=False,
        plan_fresh=False,
        plan_id=None,
        plan_requirements_sha=None,
        plan_created_at=None,
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
    # Persistence layer does not yet store plan history; return empty list to keep UI happy.
    return PlanHistoryResponse(project_id=str(project.id), entries=[])
