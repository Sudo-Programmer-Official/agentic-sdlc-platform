from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Trace
from app.db.session import get_session
from app.schemas.generation import TaskGenInput, TaskGenResponse, GeneratedTask
from app.schemas.trace import TraceOut
from app.schemas.persistence import TaskOut
from app.schemas.provenance import Provenance
from app.api.v1.health import project_health
from app.api.v1.lifecycle_score import lifecycle_score
from app.services.llm_generator import LLMTaskGenerator
from app.services.activity_log import log_activity
from app.services.ai_policy import AIPolicyError
from app.services.task_lineage import add_task_lineage_traces, derive_task_lineage

router = APIRouter(prefix="/store", tags=["generation"])
public_router = APIRouter(tags=["generation"])


async def _assert_project_doc(session: AsyncSession, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    doc = await session.get(Document, document_id)
    if not doc or doc.deleted_at or doc.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.post(
    "/projects/{project_id}/documents/{document_id}/generate-tasks",
    response_model=TaskGenResponse,
    status_code=status.HTTP_201_CREATED,
)
@public_router.post(
    "/projects/{project_id}/documents/{document_id}/generate-tasks",
    response_model=TaskGenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_tasks(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: TaskGenInput,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
) -> TaskGenResponse:
    doc = await _assert_project_doc(session, project_id, document_id)
    # Soft guard: if project health is low, require force unless skipping check
    health = await project_health(project_id, session)
    from app.core.config import get_settings

    settings = get_settings()
    lifecycle_score_resp = await lifecycle_score(project_id, session)
    if not force and lifecycle_score_resp["health_index"] < settings.health_regen_threshold:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Health index {lifecycle_score_resp['health_index']} below threshold {settings.health_regen_threshold}. Use force=true to regenerate.",
        )

    generator = LLMTaskGenerator(session=session, tenant_id=doc.tenant_id, project_id=project_id, document_id=doc.id)
    try:
        generated, prov = await generator.generate(doc.title, doc.body, payload)
    except AIPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": exc.reason,
                "next_action": exc.next_action,
                "job_id": str(exc.job_id) if exc.job_id else None,
                **exc.details,
            },
        ) from exc

    # Find previous document version for deprecation flow
    prev_doc_stmt = (
        select(Document)
        .where(
            Document.project_id == project_id,
            Document.type == doc.type,
            Document.version < doc.version,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.version.desc())
        .limit(1)
    )
    prev_doc = (await session.execute(prev_doc_stmt)).scalar_one_or_none()

    # Idempotency guard: active tasks already for this doc version
    existing_active = await session.execute(
        select(Task).where(
            Task.document_id == doc.id,
            Task.generated_from_document_version == doc.version,
            Task.status != "DEPRECATED",
            Task.deleted_at.is_(None),
        )
    )
    existing_tasks = list(existing_active.scalars().all())
    if existing_tasks and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active tasks already exist for this document version; use force=true to regenerate.",
        )
    if existing_tasks and force:
        for t in existing_tasks:
            t.status = "DEPRECATED"
            await log_activity(
                session,
                project_id=project_id,
                entity_type="task",
                entity_id=t.id,
                action_type="task.deprecated",
                event_type="force-regenerate",
                previous_state={"status": t.status},
            )

    # Deprecate tasks from previous doc version and link supersedes
    old_tasks: List[Task] = []
    if prev_doc:
        old_tasks_result = await session.execute(
            select(Task).where(
                Task.document_id == prev_doc.id,
                Task.status != "DEPRECATED",
                Task.deleted_at.is_(None),
            )
        )
        old_tasks = list(old_tasks_result.scalars().all())

    created_tasks: List[Task] = []
    for idx, gen_task in enumerate(generated):
        lineage = derive_task_lineage(document=doc, generated_task=gen_task, index=idx, provenance=prov)
        task = Task(
            tenant_id=doc.tenant_id,
            project_id=project_id,
            document_id=doc.id,
            generated_from_document_version=doc.version,
            title=gen_task.title,
            description=gen_task.description,
            category=gen_task.category,
            status="PENDING",
            source="ai",
            source_type=lineage["source_type"],
            source_node_id=lineage["source_node_id"],
            requirement_id=(lineage["derived_from_requirement_ids"][0] if lineage["derived_from_requirement_ids"] else None),
            derived_from_requirement_ids=lineage["derived_from_requirement_ids"],
            capability_id=lineage["capability_id"],
            capability_label=lineage["capability_label"],
            architecture_slice=lineage["architecture_slice"],
            impact_zone=lineage["impact_zone"],
            provenance=lineage["provenance"],
        )
        session.add(task)
        await session.flush()

        session.add(
            Trace(
                tenant_id=doc.tenant_id,
                project_id=project_id,
                from_type="document",
                from_id=doc.id,
                to_type="task",
                to_id=task.id,
                relation_type="derives",
                relation_strength=gen_task.confidence,
                ai_model_name=prov.get("ai_model_name"),
                ai_prompt_hash=prov.get("ai_prompt_hash"),
                ai_run_id=prov.get("ai_run_id"),
                confidence_score=gen_task.confidence,
                response_snapshot=prov.get("response_snapshot"),
                temperature=prov.get("temperature"),
                tokens_prompt=prov.get("tokens_prompt"),
                tokens_completion=prov.get("tokens_completion"),
            )
        )
        add_task_lineage_traces(
            session,
            task=task,
            document=doc,
            requirement_ids=lineage["derived_from_requirement_ids"],
            capability_id=lineage["capability_id"],
            confidence=gen_task.confidence,
        )

        created_tasks.append(task)

    if old_tasks:
        for old in old_tasks:
            old.status = "DEPRECATED"
            for new_task in created_tasks:
                session.add(
                    Trace(
                        tenant_id=doc.tenant_id,
                        project_id=project_id,
                        from_type="task",
                        from_id=old.id,
                        to_type="task",
                        to_id=new_task.id,
                        relation_type="supersedes",
                        relation_strength=1.0,
                    )
                )

    await log_activity(
        session,
        project_id=project_id,
        entity_type="document",
        entity_id=doc.id,
        action_type="tasks.generated",
        event_type="regenerate" if prev_doc else "generate",
        metadata={
            "model": prov.get("ai_model_name"),
            "new_tasks": len(created_tasks),
            "deprecated_tasks": len(old_tasks),
            "document_version": doc.version,
            "forced": force,
            "lineage_mode": "best_effort_v1",
            "requirements_count": len(created_tasks[0].derived_from_requirement_ids or []) if created_tasks else 0,
        },
        previous_state={"old_tasks": [str(t.id) for t in old_tasks]} if old_tasks else None,
        new_state={"new_tasks": [str(t.id) for t in created_tasks]},
    )
    await session.commit()

    return TaskGenResponse(tasks=[GeneratedTask(**t.model_dump()) for t in generated])
