from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task
from app.db.session import get_session
from app.schemas.persistence import (
    ProjectCreate,
    ProjectOut,
    DocumentCreate,
    DocumentOut,
    TaskCreate,
    TaskOut,
)
from app.services.activity_log import log_activity
from app.api.v1.schemas import (
    ProjectSummaryResponse,
    TaskCounts,
    ProjectMetricsResponse,
    PlanHistoryResponse,
)


# Legacy store prefix (DB-backed) and public projects prefix to align with UI.
router = APIRouter(prefix="/store", tags=["store"])
public_router = APIRouter(tags=["projects"])


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
@public_router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    async with session.begin():
        project = Project(name=payload.name, description=payload.description)
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
    return ProjectOut.model_validate(project)


@router.get("/projects", response_model=List[ProjectOut])
@public_router.get("/projects", response_model=List[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)) -> List[ProjectOut]:
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
@public_router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectOut.model_validate(project)


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
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    project = await session.get(Project, project_id)
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


@router.get("/projects/{project_id}/tasks", response_model=List[TaskOut])
@public_router.get("/projects/{project_id}/tasks", response_model=List[TaskOut])
async def list_tasks(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> List[TaskOut]:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    result = await session.execute(select(Task).where(Task.project_id == project_id))
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
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if payload.document_id:
        document = await session.get(Document, payload.document_id)
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        if document.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document not in project")

    async with session.begin():
        task = Task(
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
