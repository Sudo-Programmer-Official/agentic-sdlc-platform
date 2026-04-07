from __future__ import annotations

import uuid
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.models.project import Project as DBProject
from app.services import planner_service, project_service, requirements_service, run_service
from app.services.errors import ProjectNotFoundError, RequirementGraphNotFoundError
from core.models import Project as LegacyProject, Stage

PRD_DOCUMENT_TYPE = "prd"
REQUIREMENTS_DOCUMENT_TYPE = "requirements_graph"


def _map_db_status_to_legacy_stage(status_value: str | None) -> Stage:
    mapping = {
        "INTAKE": Stage.INTAKE,
        "PLAN": Stage.PLAN_READY,
        "RUN": Stage.IMPLEMENTING,
        "EVALUATE": Stage.READY_FOR_REVIEW,
    }
    return mapping.get((status_value or "").upper(), Stage.INTAKE)


async def ensure_legacy_project(session_or_project_id, project_id_or_session):
    if isinstance(session_or_project_id, AsyncSession):
        session = session_or_project_id
        project_id = project_id_or_session
    else:
        project_id = session_or_project_id
        session = project_id_or_session

    project_id_str = str(project_id)
    try:
        db_project_id = uuid.UUID(project_id_str)
    except ValueError as exc:
        raise ProjectNotFoundError(f"Project {project_id_str} not found") from exc

    db_project = await session.get(DBProject, db_project_id)
    if db_project is None or db_project.deleted_at is not None:
        raise ProjectNotFoundError(f"Project {project_id_str} not found")

    try:
        legacy_project = project_service.get_project(project_id_str)
        legacy_project.name = db_project.name
        legacy_project.description = db_project.description
        legacy_project.current_stage = _map_db_status_to_legacy_stage(db_project.status)
    except ProjectNotFoundError:
        legacy_project = LegacyProject(
            id=project_id_str,
            name=db_project.name,
            description=db_project.description,
            current_stage=_map_db_status_to_legacy_stage(db_project.status),
            created_at=db_project.created_at,
        )

    project_service._project_store.add(legacy_project)
    project_service._state_store.set_stage(project_id_str, legacy_project.current_stage)
    return legacy_project


async def persist_prd_document(
    session: AsyncSession,
    project_id: str,
    prd_text: str,
    *,
    source: str = "typed",
    created_by: str | None = "requirements-ui",
) -> Document:
    project = await _get_db_project(session, project_id)
    next_version = await _next_document_version(session, project.id, PRD_DOCUMENT_TYPE)
    title = _extract_prd_title(prd_text) or f"PRD v{next_version}"
    document = Document(
        project_id=project.id,
        tenant_id=project.tenant_id,
        type=PRD_DOCUMENT_TYPE,
        version=next_version,
        title=title,
        body=prd_text,
        content_hash=sha256(prd_text.encode("utf-8")).hexdigest(),
        source=source or "typed",
        created_by=created_by,
    )
    session.add(document)
    await session.flush()
    return document


async def sync_requirements_document(
    session: AsyncSession,
    project_id: str,
    *,
    approved_by: str | None = None,
) -> Document:
    project = await _get_db_project(session, project_id)
    graph = requirements_service.get_graph(project_id)
    body = render_requirements_document_body(graph)
    content_hash = sha256(body.encode("utf-8")).hexdigest()

    existing = await session.scalar(
        select(Document).where(
            Document.project_id == project.id,
            Document.tenant_id == project.tenant_id,
            Document.type == REQUIREMENTS_DOCUMENT_TYPE,
            Document.version == graph.version,
            Document.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.title = f"Approved requirements graph v{graph.version}"
        existing.body = body
        existing.content_hash = content_hash
        existing.source = "requirements"
        if approved_by:
            existing.created_by = approved_by
        session.add(existing)
        await session.flush()
        return existing

    document = Document(
        project_id=project.id,
        tenant_id=project.tenant_id,
        type=REQUIREMENTS_DOCUMENT_TYPE,
        version=graph.version,
        title=f"Approved requirements graph v{graph.version}",
        body=body,
        content_hash=content_hash,
        source="requirements",
        created_by=approved_by,
    )
    session.add(document)
    await session.flush()
    return document


def load_requirements_plan_state(project_id: str) -> dict:
    graph = None
    graph_hash = None
    try:
        graph = requirements_service.get_graph(project_id)
        graph_hash = graph.compute_hash()
    except RequirementGraphNotFoundError:
        graph = None
        graph_hash = None

    plan_status = run_service.get_plan_status(project_id, graph_hash)
    return {
        "graph": graph,
        "requirements_sha": graph_hash,
        "plan_status": plan_status,
        "plan_history": planner_service.list_history(project_id),
    }


def render_requirements_document_body(graph) -> str:
    lines = [
        f"# Approved Requirements Graph v{graph.version}",
        "",
        f"Status: {graph.status.value}",
    ]
    if graph.approved_by:
        lines.append(f"Approved by: {graph.approved_by}")
    if graph.approved_at:
        lines.append(f"Approved at: {graph.approved_at.isoformat()}")

    fr_nodes = [node for node in graph.nodes if node.type.value == "FR"]
    qr_nodes = [node for node in graph.nodes if node.type.value == "QR"]

    lines.extend(["", "## Functional Requirements"])
    if fr_nodes:
        for node in fr_nodes:
            lines.append(f"- {node.id}: {node.text}")
    else:
        lines.append("- None")

    lines.extend(["", "## Quality Requirements"])
    if qr_nodes:
        for node in qr_nodes:
            quality_label = f" ({node.quality_type.value})" if node.quality_type else ""
            lines.append(f"- {node.id}{quality_label}: {node.text}")
    else:
        lines.append("- None")

    lines.extend(["", "## Requirement Edges"])
    if graph.edges:
        for edge in graph.edges:
            rationale = f" Rationale: {edge.rationale}" if edge.rationale else ""
            lines.append(
                f"- {edge.from_id} {edge.relation} {edge.to_id} (weight {edge.weight:.2f}).{rationale}".rstrip()
            )
    else:
        lines.append("- None")

    return "\n".join(lines).strip() + "\n"


async def _get_db_project(session: AsyncSession, project_id: str) -> DBProject:
    await ensure_legacy_project(session, project_id)
    db_project = await session.get(DBProject, uuid.UUID(project_id))
    if db_project is None or db_project.deleted_at is not None:
        raise ProjectNotFoundError(f"Project {project_id} not found")
    return db_project


async def _next_document_version(session: AsyncSession, project_id: uuid.UUID, document_type: str) -> int:
    current_version = await session.scalar(
        select(Document.version)
        .where(Document.project_id == project_id, Document.type == document_type, Document.deleted_at.is_(None))
        .order_by(Document.version.desc())
        .limit(1)
    )
    return int(current_version or 0) + 1


def _extract_prd_title(prd_text: str) -> str | None:
    for line in prd_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.startswith("#"):
            return cleaned.lstrip("#").strip() or None
        return cleaned[:255]
    return None
