from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Task, Document, Artifact, Trace, Approval
from app.db.session import get_session
from app.schemas.trace import TraceCreate, TraceOut
from app.schemas.artifact import ArtifactCreate, ArtifactOut
from app.schemas.approval import ApprovalCreate, ApprovalOut
from app.schemas.graph import GraphResult, GraphNode, GraphEdge
from app.schemas.provenance import Provenance
from app.schemas.explain import ExplainTaskResponse

router = APIRouter(prefix="/store", tags=["store-graph"])


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
            | (Trace.from_id.in_(select(Document.id).where(Document.project_id == project_id)))
            | (Trace.from_id.in_(select(Task.id).where(Task.project_id == project_id)))
            | (Trace.from_id.in_(select(Artifact.id).where(Artifact.project_id == project_id)))
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

    artifact = Artifact(
        project_id=project_id,
        task_id=payload.task_id,
        type=payload.type,
        uri=payload.uri,
        version=payload.version,
        extra_metadata=payload.metadata,
    )
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return ArtifactOut.model_validate(artifact)


@router.get("/projects/{project_id}/artifacts", response_model=List[ArtifactOut])
async def list_artifacts(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> List[ArtifactOut]:
    await _assert_project(session, project_id)
    result = await session.execute(select(Artifact).where(Artifact.project_id == project_id))
    artifacts = result.scalars().all()
    return [ArtifactOut.model_validate(a) for a in artifacts]


@router.post(
    "/projects/{project_id}/approvals",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_approval(
    project_id: uuid.UUID,
    payload: ApprovalCreate,
    session: AsyncSession = Depends(get_session),
) -> ApprovalOut:
    await _assert_project(session, project_id)
    approval = Approval(
        project_id=project_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        status=payload.status,
        decided_by=payload.decided_by,
        comment=payload.comment,
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    return ApprovalOut.model_validate(approval)


@router.get("/projects/{project_id}/approvals", response_model=List[ApprovalOut])
async def list_approvals(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> List[ApprovalOut]:
    await _assert_project(session, project_id)
    result = await session.execute(select(Approval).where(Approval.project_id == project_id))
    approvals = result.scalars().all()
    return [ApprovalOut.model_validate(a) for a in approvals]


# ---------------------------
# Graph traversal / impact
# ---------------------------

ENTITY_TABLES = {
    "project": Project,
    "document": Document,
    "task": Task,
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
            label = getattr(entity, "name", None) or getattr(entity, "title", None) or str(current_id)
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


# ---------------------------
# Document history
# ---------------------------

@router.get(
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
