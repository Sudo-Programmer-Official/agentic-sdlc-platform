from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Task, Trace


NODE_UUID_NAMESPACE = uuid.UUID("6d5a2718-d42d-4e62-97f0-63ed1d908f46")
REQUIREMENT_LINE_RE = re.compile(r"^\s*-\s*((?:FR|QR|NFR|REQ)[-_]?\d+)\s*:?", re.IGNORECASE)


def stable_node_uuid(project_id: uuid.UUID, node_type: str, node_id: str) -> uuid.UUID:
    return uuid.uuid5(NODE_UUID_NAMESPACE, f"{project_id}:{node_type}:{node_id.strip().upper()}")


def extract_requirement_ids_from_document(document: Document) -> list[str]:
    if document.type != "requirements_graph":
        return []
    ids: list[str] = []
    for line in (document.body or "").splitlines():
        match = REQUIREMENT_LINE_RE.match(line)
        if not match:
            continue
        req_id = match.group(1).replace("_", "-").upper()
        if req_id not in ids:
            ids.append(req_id)
    return ids


def _architecture_slice(title: str, category: str | None) -> str:
    text = f"{title} {category or ''}".lower()
    if any(token in text for token in ("frontend", "ui", "page", "hero", "footer", "css", "html")):
        return "frontend"
    if any(token in text for token in ("api", "backend", "server", "database", "db")):
        return "backend"
    if any(token in text for token in ("test", "validate", "quality", "qa")):
        return "validation"
    if any(token in text for token in ("deploy", "ci", "docker", "infra", "env")):
        return "platform"
    return "application"


def _impact_zone(architecture_slice: str) -> list[str]:
    if architecture_slice == "frontend":
        return ["apps/web"]
    if architecture_slice == "backend":
        return ["apps/api"]
    if architecture_slice == "validation":
        return ["tests"]
    if architecture_slice == "platform":
        return ["infra", ".github/workflows"]
    return []


def derive_task_lineage(
    *,
    document: Document,
    generated_task: Any,
    index: int,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requirement_ids = extract_requirement_ids_from_document(document)
    source_type = "requirement_propagation" if requirement_ids else "document_generation"
    capability_id = f"CAP-{index + 1:03d}" if requirement_ids else None
    title = str(getattr(generated_task, "title", "") or "")
    category = getattr(generated_task, "category", None)
    architecture_slice = _architecture_slice(title, category)
    lineage_provenance = {
        "lineage_mode": "best_effort_v1",
        "document_id": str(document.id),
        "document_type": document.type,
        "document_version": document.version,
        "requirements_count": len(requirement_ids),
        "ai_model_name": (provenance or {}).get("ai_model_name"),
    }
    return {
        "source_type": source_type,
        "source_node_id": str(document.id),
        "derived_from_requirement_ids": requirement_ids,
        "capability_id": capability_id,
        "capability_label": title[:255] if capability_id else None,
        "architecture_slice": architecture_slice,
        "impact_zone": _impact_zone(architecture_slice),
        "provenance": lineage_provenance,
    }


def add_task_lineage_traces(
    session: AsyncSession,
    *,
    task: Task,
    document: Document,
    requirement_ids: list[str] | None,
    capability_id: str | None,
    confidence: float | None,
) -> None:
    for req_id in requirement_ids or []:
        session.add(
            Trace(
                tenant_id=task.tenant_id,
                project_id=task.project_id,
                from_type="requirement",
                from_id=stable_node_uuid(task.project_id, "requirement", req_id),
                to_type="task",
                to_id=task.id,
                relation_type="satisfies",
                relation_strength=confidence,
                confidence_score=confidence,
                response_snapshot={
                    "requirement_id": req_id,
                    "document_id": str(document.id),
                    "lineage_mode": "best_effort_v1",
                },
            )
        )
    if capability_id:
        session.add(
            Trace(
                tenant_id=task.tenant_id,
                project_id=task.project_id,
                from_type="capability",
                from_id=stable_node_uuid(task.project_id, "capability", capability_id),
                to_type="task",
                to_id=task.id,
                relation_type="decomposes_to",
                relation_strength=confidence,
                confidence_score=confidence,
                response_snapshot={
                    "capability_id": capability_id,
                    "document_id": str(document.id),
                    "lineage_mode": "best_effort_v1",
                },
            )
        )
