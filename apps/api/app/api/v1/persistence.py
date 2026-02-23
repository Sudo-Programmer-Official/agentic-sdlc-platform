from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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


router = APIRouter(prefix="/store", tags=["store"])


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
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
async def list_projects(session: AsyncSession = Depends(get_session)) -> List[ProjectOut]:
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
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
