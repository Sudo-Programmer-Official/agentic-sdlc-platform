from __future__ import annotations

from datetime import datetime, UTC
import uuid
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.db.models import Project, Task, Document, Artifact, Trace, Approval, Run, WorkItem
from app.db.session import get_session
from app.core.config import get_settings
from app.api.v1.health import project_health
from app.schemas.trace import TraceCreate, TraceOut
from app.schemas.artifact import ArtifactCreate, ArtifactOut
from app.schemas.approval import ApprovalCreate, ApprovalOut
from app.schemas.graph import GraphResult, GraphNode, GraphEdge
from app.schemas.graph_context import GraphContextResponse
from app.schemas.provenance import Provenance
from app.schemas.explain import ExplainArtifactResponse, ExplainTaskResponse
from app.schemas.artifact_diff import ArtifactDiffResponse
from app.schemas.persistence import DocumentOut, RunOut, TaskOut, WorkItemOut
from app.services.artifact_diff import build_artifact_diff_preview
from app.services.event_log import record_event
from app.services.graph_context import build_graph_context
from app.services.run_summary_builder import upsert_run_summary
from app.services.activity_log import log_activity

router = APIRouter(prefix="/store", tags=["store-graph"])
public_router = APIRouter(tags=["graph"])


async def _assert_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post(
    "/projects/{project_id}/traces",
    response_model=TraceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_trace(
    project_id: uuid.UUID,
    payload: TraceCreate,
    session: AsyncSession = Depends(get_session),
) -> TraceOut:
    await _assert_project(session, project_id)
    settings = get_settings()
    if settings.health_cycles_block:
        health = await project_health(project_id, session)
        if health.get("graph_cycles_detected"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cycles detected in graph; trace creation blocked until resolved (or disable health_cycles_block).",
            )
    trace = Trace(
        project_id=project_id,
        from_type=payload.from_type,
        from_id=payload.from_id,
        to_type=payload.to_type,
        to_id=payload.to_id,
        relation_type=payload.relation_type,
        relation_strength=payload.relation_strength,
    )
    session.add(trace)
    await session.commit()
    await session.refresh(trace)
    return TraceOut.model_validate(trace)


@router.get("/projects/{project_id}/traces", response_model=List[TraceOut])
async def list_traces(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> List[TraceOut]:
    await _assert_project(session, project_id)
    result = await session.execute(
        select(Trace).where(
            (Trace.from_id == project_id)  # project-level traces uncommon
            | (Trace.to_id == project_id)
            | (Trace.from_id.in_(select(Run.id).where(Run.project_id == project_id)))
            | (Trace.from_id.in_(select(WorkItem.id).where(WorkItem.project_id == project_id)))
            | (Trace.from_id.in_(select(Document.id).where(Document.project_id == project_id)))
            | (Trace.from_id.in_(select(Task.id).where(Task.project_id == project_id)))
            | (Trace.from_id.in_(select(Artifact.id).where(Artifact.project_id == project_id)))
            | (Trace.to_id.in_(select(Run.id).where(Run.project_id == project_id)))
            | (Trace.to_id.in_(select(WorkItem.id).where(WorkItem.project_id == project_id)))
            | (Trace.to_id.in_(select(Document.id).where(Document.project_id == project_id)))
            | (Trace.to_id.in_(select(Task.id).where(Task.project_id == project_id)))
            | (Trace.to_id.in_(select(Artifact.id).where(Artifact.project_id == project_id)))
        )
    )
    traces = result.scalars().all()
    return [TraceOut.model_validate(t) for t in traces]


@router.post(
    "/projects/{project_id}/artifacts",
    response_model=ArtifactOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_artifact(
    project_id: uuid.UUID,
    payload: ArtifactCreate,
    session: AsyncSession = Depends(get_session),
) -> ArtifactOut:
    await _assert_project(session, project_id)

    if payload.task_id:
        task = await session.get(Task, payload.task_id)
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if task.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task not in project")

    run = None
    if payload.run_id:
        run = await session.get(Run, payload.run_id)
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if run.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run not in project")

    work_item = None
    if payload.work_item_id:
        work_item = await session.get(WorkItem, payload.work_item_id)
        if not work_item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
        if work_item.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Work item not in project")
        if run and work_item.run_id != run.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Work item does not belong to run")

    artifact = Artifact(
        project_id=project_id,
        task_id=payload.task_id,
        run_id=payload.run_id or (work_item.run_id if work_item else None),
        work_item_id=payload.work_item_id,
        type=payload.type,
        uri=payload.uri,
        version=payload.version,
        extra_metadata=payload.metadata,
    )
    session.add(artifact)
    await session.flush()
    if work_item:
        session.add(
            Trace(
                project_id=project_id,
                from_type="work_item",
                from_id=work_item.id,
                to_type="artifact",
                to_id=artifact.id,
                relation_type="produces",
                relation_strength=1.0,
            )
        )
    await session.commit()
    await session.refresh(artifact)
    return ArtifactOut.model_validate(artifact)


@router.get("/projects/{project_id}/artifacts", response_model=List[ArtifactOut])
@public_router.get("/projects/{project_id}/artifacts", response_model=List[ArtifactOut])
async def list_artifacts(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> List[ArtifactOut]:
    await _assert_project(session, project_id)
    result = await session.execute(select(Artifact).where(Artifact.project_id == project_id))
    artifacts = result.scalars().all()
    return [ArtifactOut.model_validate(a) for a in artifacts]


@router.get("/projects/{project_id}/artifacts/{artifact_id}/diff", response_model=ArtifactDiffResponse)
@public_router.get("/projects/{project_id}/artifacts/{artifact_id}/diff", response_model=ArtifactDiffResponse)
async def preview_artifact_diff(
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ArtifactDiffResponse:
    try:
        return await build_artifact_diff_preview(session, project_id=project_id, artifact_id=artifact_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND if detail == "Artifact not found" else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post(
    "/projects/{project_id}/approvals",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
)
@public_router.post(
    "/projects/{project_id}/approvals",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_approval(
    project_id: uuid.UUID,
    payload: ApprovalCreate,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> ApprovalOut:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    target: Artifact | Task | Document | None = None
    if payload.target_type == "artifact":
        target = await session.scalar(
            select(Artifact).where(
                Artifact.id == payload.target_id,
                Artifact.project_id == project_id,
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.deleted_at.is_(None),
            )
        )
    elif payload.target_type == "task":
        target = await session.scalar(
            select(Task).where(
                Task.id == payload.target_id,
                Task.project_id == project_id,
                Task.tenant_id == ctx.tenant_id,
                Task.deleted_at.is_(None),
            )
        )
    elif payload.target_type == "document":
        target = await session.scalar(
            select(Document).where(
                Document.id == payload.target_id,
                Document.project_id == project_id,
                Document.tenant_id == ctx.tenant_id,
                Document.deleted_at.is_(None),
            )
        )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported approval target_type")

    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval target not found")

    approval = Approval(
        tenant_id=ctx.tenant_id,
        project_id=project_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        status=payload.status.strip().upper(),
        decided_by=payload.decided_by,
        decided_at=datetime.now(UTC).isoformat() if payload.status.strip().upper() != "PENDING" else None,
        comment=payload.comment,
    )
    session.add(approval)
    await session.flush()

    target_run_id: uuid.UUID | None = None
    if payload.target_type == "artifact":
        artifact = target
        target_run_id = artifact.run_id
    await log_activity(
        session,
        project_id=project_id,
        entity_type=payload.target_type,
        entity_id=payload.target_id,
        action_type="approval.recorded",
        metadata={
            "status": approval.status,
            "target_type": payload.target_type,
            "decided_by": payload.decided_by,
        },
        actor=ctx.user_id,
    )
    if target_run_id:
        await record_event(
            session,
            project_id=project_id,
            run_id=target_run_id,
            event_type="RUN_APPROVAL_RECORDED",
            actor_type="USER",
            actor_id=ctx.user_id,
            message=f"{payload.target_type.title()} {approval.status.lower()}",
            payload={
                "target_type": payload.target_type,
                "target_id": str(payload.target_id),
                "status": approval.status,
                "comment": payload.comment,
            },
            tenant_id=ctx.tenant_id,
        )
        await upsert_run_summary(session, target_run_id)
    await session.commit()
    await session.refresh(approval)
    return ApprovalOut.model_validate(approval)


@router.get("/projects/{project_id}/approvals", response_model=List[ApprovalOut])
@public_router.get("/projects/{project_id}/approvals", response_model=List[ApprovalOut])
async def list_approvals(
    project_id: uuid.UUID,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    ctx=Depends(get_tenant_context),
    session: AsyncSession = Depends(get_session),
) -> List[ApprovalOut]:
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    stmt = (
        select(Approval)
        .where(
            Approval.project_id == project_id,
            Approval.tenant_id == ctx.tenant_id,
            Approval.deleted_at.is_(None),
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
    )
    if target_type:
        stmt = stmt.where(Approval.target_type == target_type)
    if target_id:
        stmt = stmt.where(Approval.target_id == target_id)
    result = await session.execute(stmt)
    approvals = result.scalars().all()
    return [ApprovalOut.model_validate(a) for a in approvals]


# ---------------------------
# Graph traversal / impact
# ---------------------------

ENTITY_TABLES = {
    "project": Project,
    "document": Document,
    "task": Task,
    "run": Run,
    "work_item": WorkItem,
    "artifact": Artifact,
}


async def load_entity(session: AsyncSession, entity_type: str, entity_id: uuid.UUID):
    model = ENTITY_TABLES.get(entity_type)
    if not model:
        return None
    obj = await session.get(model, entity_id)
    if not obj or getattr(obj, "deleted_at", None):
        return None
    return obj


def _entity_label(entity) -> str:
    return (
        getattr(entity, "name", None)
        or getattr(entity, "title", None)
        or getattr(entity, "key", None)
        or getattr(entity, "type", None)
        or getattr(entity, "status", None)
        or str(getattr(entity, "id"))
    )


async def fetch_traces_batch(
    session: AsyncSession,
    ids: List[uuid.UUID],
    direction: str,
    relation_types: Optional[List[str]],
) -> List[Trace]:
    if not ids:
        return []
    filters = [
        Trace.deleted_at.is_(None),
        Trace.relation_type.in_(relation_types) if relation_types else True,
    ]
    if direction == "forward":
        filters.append(Trace.from_id.in_(ids))
    else:
        filters.append(Trace.to_id.in_(ids))

    stmt = select(Trace).where(and_(*filters))
    result = await session.execute(stmt)
    return result.scalars().all()


async def bfs(
    session: AsyncSession,
    start_type: str,
    start_id: uuid.UUID,
    project_id: uuid.UUID,
    direction: str,
    max_depth: int = 3,
    max_nodes: int = 500,
    relation_types: Optional[List[str]] = None,
) -> GraphResult:
    visited: set[Tuple[str, uuid.UUID]] = set()
    edges: list[GraphEdge] = []
    nodes: dict[Tuple[str, uuid.UUID], GraphNode] = {}

    frontier: list[Tuple[str, uuid.UUID]] = [(start_type, start_id)]
    depth = 0

    while frontier and depth <= max_depth and len(nodes) < max_nodes:
        ids = [fid for _, fid in frontier]
        traces = await fetch_traces_batch(session, ids, direction, relation_types)

        next_frontier: list[Tuple[str, uuid.UUID]] = []
        for current_type, current_id in frontier:
            if (current_type, current_id) in visited:
                continue
            entity = await load_entity(session, current_type, current_id)
            visited.add((current_type, current_id))
            if not entity:
                continue
            label = _entity_label(entity)
            nodes[(current_type, current_id)] = GraphNode(
                id=current_id, type=current_type, label=label, meta=None
            )

        if depth == max_depth or len(nodes) >= max_nodes:
            break

        for trace in traces:
            if direction == "forward":
                neighbor_type = trace.to_type
                neighbor_id = trace.to_id
                edge = GraphEdge(
                    from_id=trace.from_id,
                    to_id=trace.to_id,
                    relation_type=trace.relation_type,
                    relation_strength=trace.relation_strength,
                    depth=depth + 1,
                    direction="forward",
                )
            else:
                neighbor_type = trace.from_type
                neighbor_id = trace.from_id
                edge = GraphEdge(
                    from_id=trace.from_id,
                    to_id=trace.to_id,
                    relation_type=trace.relation_type,
                    relation_strength=trace.relation_strength,
                    depth=depth + 1,
                    direction="backward",
                )

            neighbor_obj = await load_entity(session, neighbor_type, neighbor_id)
            if not neighbor_obj:
                continue
            proj_id = getattr(neighbor_obj, "project_id", None) or getattr(neighbor_obj, "id", None)
            if proj_id and proj_id != project_id:
                continue

            edges.append(edge)
            if (neighbor_type, neighbor_id) not in visited:
                next_frontier.append((neighbor_type, neighbor_id))

        frontier = next_frontier
        depth += 1
        if len(nodes) >= max_nodes:
            break

    depth_reached = depth
    if len(nodes) >= max_nodes:
        depth_reached = depth  # capped

    return GraphResult(nodes=list(nodes.values()), edges=edges, depth_reached=depth_reached)


@router.get(
    "/projects/{project_id}/impact/{entity_type}/{entity_id}",
    response_model=GraphResult,
)
async def impact_analysis(
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    max_depth: int = 3,
    max_nodes: int = 500,
    relation_types: Optional[List[str]] = None,
    session: AsyncSession = Depends(get_session),
) -> GraphResult:
    await _assert_project(session, project_id)
    return await bfs(
        session=session,
        start_type=entity_type,
        start_id=entity_id,
        project_id=project_id,
        direction="forward",
        max_depth=max_depth,
        max_nodes=max_nodes,
        relation_types=relation_types,
    )


@router.get(
    "/projects/{project_id}/backtrace/{entity_type}/{entity_id}",
    response_model=GraphResult,
)
async def backtrace_analysis(
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    max_depth: int = 3,
    max_nodes: int = 500,
    relation_types: Optional[List[str]] = None,
    session: AsyncSession = Depends(get_session),
) -> GraphResult:
    await _assert_project(session, project_id)
    return await bfs(
        session=session,
        start_type=entity_type,
        start_id=entity_id,
        project_id=project_id,
        direction="backward",
        max_depth=max_depth,
        max_nodes=max_nodes,
        relation_types=relation_types,
    )


@router.get(
    "/projects/{project_id}/graph/context/{entity_type}/{entity_id}",
    response_model=GraphContextResponse,
)
@public_router.get(
    "/projects/{project_id}/graph/context/{entity_type}/{entity_id}",
    response_model=GraphContextResponse,
)
async def graph_context(
    project_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    max_depth: int = 4,
    session: AsyncSession = Depends(get_session),
) -> GraphContextResponse:
    await _assert_project(session, project_id)
    try:
        return await build_graph_context(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            max_depth=max_depth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/artifacts/context",
    response_model=GraphContextResponse,
)
@public_router.get(
    "/projects/{project_id}/artifacts/context",
    response_model=GraphContextResponse,
)
async def artifact_context_by_uri(
    project_id: uuid.UUID,
    uri: str = Query(..., min_length=1),
    max_depth: int = 4,
    session: AsyncSession = Depends(get_session),
) -> GraphContextResponse:
    await _assert_project(session, project_id)
    artifact = await session.scalar(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.uri == uri,
            Artifact.deleted_at.is_(None),
        )
        .order_by(Artifact.version.desc(), Artifact.created_at.desc())
    )
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found for uri")
    return await build_graph_context(
        session,
        entity_type="artifact",
        entity_id=artifact.id,
        project_id=project_id,
        max_depth=max_depth,
    )


# ---------------------------
# Document history
# ---------------------------

@router.get(
    "/projects/{project_id}/documents/{document_id}/history",
    response_model=List[DocumentOut],
)
@public_router.get(
    "/projects/{project_id}/documents/{document_id}/history",
    response_model=List[DocumentOut],
)
async def document_history(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> List[DocumentOut]:
    doc = await session.get(Document, document_id)
    if not doc or doc.project_id != project_id or doc.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stmt = (
        select(Document)
        .where(
            Document.project_id == project_id,
            Document.type == doc.type,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.version.asc())
    )
    result = await session.execute(stmt)
    docs = result.scalars().all()
    return [DocumentOut.model_validate(d) for d in docs]


# ---------------------------
# Explain Task
# ---------------------------

@router.get(
    "/projects/{project_id}/tasks/{task_id}/explain",
    response_model=ExplainTaskResponse,
)
@public_router.get(
    "/projects/{project_id}/tasks/{task_id}/explain",
    response_model=ExplainTaskResponse,
)
async def explain_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    max_depth: int = 4,
    max_nodes: int = 500,
    session: AsyncSession = Depends(get_session),
) -> ExplainTaskResponse:
    task = await session.get(Task, task_id)
    if not task or task.project_id != project_id or task.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Backtrace to find origin docs and provenance
    graph = await bfs(
        session=session,
        start_type="task",
        start_id=task_id,
        project_id=project_id,
        direction="backward",
        max_depth=max_depth,
        max_nodes=max_nodes,
        relation_types=None,
    )

    # Origin documents = documents in graph
    origin_docs = []
    doc_ids = {n.id for n in graph.nodes if n.type == "document"}
    if doc_ids:
        stmt = select(Document).where(Document.id.in_(doc_ids), Document.deleted_at.is_(None))
        res = await session.execute(stmt)
        origin_docs = [DocumentOut.model_validate(d) for d in res.scalars().all()]

    # Artifacts directly attached to task
    art_res = await session.execute(
        select(Artifact).where(Artifact.task_id == task_id, Artifact.deleted_at.is_(None))
    )
    artifacts = [ArtifactOut.model_validate(a) for a in art_res.scalars().all()]

    # Approvals targeting this task
    appr_res = await session.execute(
        select(Approval).where(
            Approval.project_id == project_id,
            Approval.target_type == "task",
            Approval.target_id == task_id,
            Approval.deleted_at.is_(None),
        )
    )
    approvals = [ApprovalOut.model_validate(a) for a in appr_res.scalars().all()]

    # Provenance: pick from traces involving this task with AI fields
    prov_stmt = select(Trace).where(
        Trace.deleted_at.is_(None),
        Trace.project_id == project_id,
        (Trace.from_id == task_id) | (Trace.to_id == task_id),
    )
    prov_res = await session.execute(prov_stmt)
    provenance = None
    confidence = None
    prov_records = []
    for t in prov_res.scalars().all():
        if any([t.ai_model_name, t.ai_prompt_hash, t.ai_run_id, t.confidence_score]):
            provenance = Provenance(
                ai_model_name=t.ai_model_name,
                ai_prompt_hash=t.ai_prompt_hash,
                ai_run_id=t.ai_run_id,
                confidence_score=t.confidence_score,
            )
            confidence = t.confidence_score
            prov_records.append(t)
            break

    # Supersede depth and origin chain
    supersede_depth = 0
    visited_sup = set()

    async def supersede_walk(target_id: uuid.UUID, depth: int):
        nonlocal supersede_depth
        if target_id in visited_sup:
            return
        visited_sup.add(target_id)
        supersede_depth = max(supersede_depth, depth)
        parents_res = await session.execute(
            select(Trace.from_id).where(
                Trace.to_id == target_id,
                Trace.relation_type == "supersedes",
                Trace.deleted_at.is_(None),
            )
        )
        parents = [row[0] for row in parents_res.fetchall()]
        for p in parents:
            await supersede_walk(p, depth + 1)

    await supersede_walk(task_id, 0)

    doc_chain = sorted(
        origin_docs,
        key=lambda d: d.version if hasattr(d, "version") else 0,
    )

    confs = [t.confidence_score for t in prov_records if t.confidence_score is not None]
    confidence_aggregate = sum(confs) / len(confs) if confs else confidence

    provenance_summary = None
    if prov_records:
        provenance_summary = {
            "models": list({t.ai_model_name for t in prov_records if t.ai_model_name}),
            "generation_runs": len(prov_records),
            "avg_confidence": confidence_aggregate,
        }

    regen_edges = await session.scalar(
        select(func.count()).select_from(
            select(Trace.id)
            .where(
                Trace.project_id == project_id,
                Trace.relation_type == "supersedes",
                ((Trace.to_id == task_id) | (Trace.from_id == task_id)),
                Trace.deleted_at.is_(None),
            )
            .subquery()
        )
    )
    regeneration_history = {"supersede_edges": regen_edges or 0}

    return ExplainTaskResponse(
        task=TaskOut.model_validate(task),
        origin_documents=origin_docs,
        artifacts=artifacts,
        approvals=approvals,
        graph=graph,
        provenance=provenance,
        confidence_score=confidence,
        supersede_depth=supersede_depth,
        origin_document_chain=[DocumentOut.model_validate(d) for d in doc_chain],
        confidence_aggregate=confidence_aggregate,
        provenance_summary=provenance_summary,
        regeneration_history=regeneration_history,
    )


@router.get(
    "/projects/{project_id}/artifacts/{artifact_id}/explain",
    response_model=ExplainArtifactResponse,
)
@public_router.get(
    "/projects/{project_id}/artifacts/{artifact_id}/explain",
    response_model=ExplainArtifactResponse,
)
async def explain_artifact(
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
    max_depth: int = 4,
    session: AsyncSession = Depends(get_session),
) -> ExplainArtifactResponse:
    artifact = await session.get(Artifact, artifact_id)
    if not artifact or artifact.project_id != project_id or artifact.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    context = await build_graph_context(
        session,
        entity_type="artifact",
        entity_id=artifact_id,
        project_id=project_id,
        max_depth=max_depth,
    )

    task = await session.get(Task, artifact.task_id) if artifact.task_id else None
    run = await session.get(Run, artifact.run_id) if artifact.run_id else None
    work_item = await session.get(WorkItem, artifact.work_item_id) if artifact.work_item_id else None

    origin_doc_ids = {node.id for node in context.ancestors if node.type == "document"}
    origin_docs: list[DocumentOut] = []
    if origin_doc_ids:
        docs = (
            await session.execute(
                select(Document).where(Document.id.in_(origin_doc_ids), Document.deleted_at.is_(None))
            )
        ).scalars().all()
        origin_docs = [DocumentOut.model_validate(doc) for doc in docs]

    approval_rows = (
        await session.execute(
            select(Approval).where(
                Approval.project_id == project_id,
                Approval.target_type == "artifact",
                Approval.target_id == artifact_id,
                Approval.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    approvals = [ApprovalOut.model_validate(approval) for approval in approval_rows]

    prov_rows = (
        await session.execute(
            select(Trace).where(
                Trace.project_id == project_id,
                Trace.deleted_at.is_(None),
                ((Trace.from_type == "artifact") & (Trace.from_id == artifact_id))
                | ((Trace.to_type == "artifact") & (Trace.to_id == artifact_id)),
            )
        )
    ).scalars().all()
    provenance = None
    confidence = None
    for trace in prov_rows:
        if any([trace.ai_model_name, trace.ai_prompt_hash, trace.ai_run_id, trace.confidence_score]):
            provenance = Provenance(
                ai_model_name=trace.ai_model_name,
                ai_prompt_hash=trace.ai_prompt_hash,
                ai_run_id=trace.ai_run_id,
                confidence_score=trace.confidence_score,
            )
            confidence = trace.confidence_score
            break

    lineage_summary = {
        "origin_document_count": len(origin_docs),
        "has_task": task is not None,
        "has_run": run is not None,
        "has_work_item": work_item is not None,
        "uri": artifact.uri,
        "artifact_type": artifact.type,
    }

    return ExplainArtifactResponse(
        artifact=ArtifactOut.model_validate(artifact),
        task=TaskOut.model_validate(task) if task else None,
        run=RunOut.model_validate(run) if run else None,
        work_item=WorkItemOut.model_validate(work_item) if work_item else None,
        origin_documents=origin_docs,
        approvals=approvals,
        context=context,
        provenance=provenance,
        confidence_score=confidence,
        lineage_summary=lineage_summary,
    )
