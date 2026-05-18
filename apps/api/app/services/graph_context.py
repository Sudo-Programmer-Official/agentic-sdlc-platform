from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, Document, Project, Run, Task, Trace, WorkItem
from app.schemas.graph import GraphEdge, GraphNode
from app.schemas.graph_context import GraphContextBudget, GraphContextResponse


ENTITY_TABLES = {
    "project": Project,
    "document": Document,
    "task": Task,
    "run": Run,
    "work_item": WorkItem,
    "artifact": Artifact,
}

_TYPE_ORDER = {
    "project": 0,
    "document": 1,
    "task": 2,
    "run": 3,
    "work_item": 4,
    "artifact": 5,
}


@dataclass(frozen=True)
class GraphContextLimits:
    max_depth: int = 4
    max_ancestor_nodes: int = 10
    max_descendant_nodes: int = 6
    max_edges: int = 24
    max_documents: int = 3
    max_tasks: int = 5
    max_artifacts: int = 5
    max_runs: int = 3
    max_work_items: int = 5


DEFAULT_CONTEXT_LIMITS = GraphContextLimits()
EXECUTOR_CONTEXT_LIMITS = GraphContextLimits(
    max_depth=3,
    max_ancestor_nodes=6,
    max_descendant_nodes=3,
    max_edges=14,
    max_documents=2,
    max_tasks=4,
    max_artifacts=3,
    max_runs=2,
    max_work_items=4,
)


async def load_entity(session: AsyncSession, entity_type: str, entity_id: uuid.UUID):
    model = ENTITY_TABLES.get(entity_type)
    if not model:
        return None
    entity = await session.get(model, entity_id)
    if not entity:
        return None
    if getattr(entity, "deleted_at", None):
        return None
    return entity


def _entity_label(entity) -> str:
    return (
        getattr(entity, "name", None)
        or getattr(entity, "title", None)
        or getattr(entity, "key", None)
        or getattr(entity, "type", None)
        or getattr(entity, "status", None)
        or str(getattr(entity, "id"))
    )


def _keyword_domain(text: str) -> str | None:
    lowered = text.lower()
    if any(token in lowered for token in ("auth", "security", "login", "permission", "token")):
        return "security"
    if any(token in lowered for token in ("ui", "frontend", "page", "component", "browser")):
        return "frontend"
    if any(token in lowered for token in ("api", "backend", "database", "sql", "queue", "worker", "runtime")):
        return "backend"
    if any(token in lowered for token in ("test", "pytest", "spec", "coverage", "assert")):
        return "quality"
    if any(token in lowered for token in ("deploy", "ecs", "docker", "ci", "workflow")):
        return "delivery"
    return None


def _risk_level(text: str) -> str | None:
    lowered = text.lower()
    if any(token in lowered for token in ("security", "auth", "payment", "credential", "secret")):
        return "high"
    if any(token in lowered for token in ("deploy", "migration", "schema", "runtime", "worker")):
        return "medium"
    return None


def _language_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    path = PurePosixPath(uri.split("://", 1)[-1])
    suffix = path.suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".vue": "vue",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(suffix)


def _derive_semantics(entity_type: str, entity) -> dict[str, Any]:
    if entity_type == "project":
        text = f"{getattr(entity, 'name', '')} {getattr(entity, 'description', '')}"
        return {
            "node_type": "project",
            "domain": _keyword_domain(text),
            "intent": getattr(entity, "name", None),
            "risk": _risk_level(text),
            "status": getattr(entity, "status", None),
        }
    if entity_type == "document":
        text = f"{entity.title} {entity.body}"
        return {
            "node_type": "document",
            "subtype": entity.type,
            "domain": _keyword_domain(text),
            "intent": entity.title,
            "risk": _risk_level(text),
            "version": entity.version,
            "source": entity.source,
        }
    if entity_type == "task":
        text = f"{entity.title} {entity.description or ''} {entity.category}"
        return {
            "node_type": "task",
            "subtype": entity.category,
            "domain": _keyword_domain(text),
            "intent": entity.title,
            "risk": _risk_level(text),
            "capability": entity.category,
            "stage": entity.stage,
            "status": entity.status,
            "source": entity.source,
        }
    if entity_type == "run":
        return {
            "node_type": "run",
            "intent": f"Run via {entity.executor}",
            "capability": entity.executor,
            "status": entity.status,
        }
    if entity_type == "work_item":
        text = f"{entity.type} {entity.key or ''} {entity.executor}"
        capability = {
            "PLAN_DAG": "planning",
            "PLAN_BACKEND_TOPOLOGY": "planning",
            "CODE_BACKEND": "backend_code",
            "GENERATE_ROUTE": "backend_code",
            "GENERATE_SERVICE": "backend_code",
            "GENERATE_REPOSITORY": "backend_code",
            "GENERATE_CAPABILITY_BINDING": "backend_code",
            "CODE_FRONTEND": "frontend_code",
            "WRITE_TESTS": "testing",
            "RUN_TESTS": "testing",
            "REVIEW_DIFF": "review",
            "REVIEW_INTEGRATION": "review",
            "FIX_TEST_FAILURE": "bugfix",
        }.get(entity.type, entity.executor)
        return {
            "node_type": "work_item",
            "subtype": entity.type,
            "domain": _keyword_domain(text),
            "intent": entity.key or entity.type,
            "risk": _risk_level(text),
            "capability": capability,
            "executor": entity.executor,
            "status": entity.status,
        }
    if entity_type == "artifact":
        meta = entity.extra_metadata or {}
        uri = entity.uri
        return {
            "node_type": "artifact",
            "subtype": entity.type,
            "intent": meta.get("intent") or entity.type,
            "domain": _keyword_domain(f"{entity.type} {uri}"),
            "risk": _risk_level(f"{entity.type} {uri}"),
            "language": meta.get("language") or _language_from_uri(uri),
            "module": meta.get("module") or PurePosixPath(uri.split("://", 1)[-1]).name,
        }
    return {"node_type": entity_type}


def _entity_summary(entity_type: str, entity) -> str | None:
    if entity_type == "document":
        return f"{entity.title} (v{entity.version}, {entity.type})"
    if entity_type == "task":
        return f"{entity.title} [{entity.stage}/{entity.status}]"
    if entity_type == "run":
        return f"{entity.status} via {entity.executor}"
    if entity_type == "work_item":
        return f"{entity.type} [{entity.status}] via {entity.executor}"
    if entity_type == "artifact":
        return f"{entity.type} -> {entity.uri}"
    if entity_type == "project":
        return getattr(entity, "description", None)
    return None


def _to_graph_node(entity_type: str, entity) -> GraphNode:
    summary = _entity_summary(entity_type, entity)
    semantics = _derive_semantics(entity_type, entity)
    meta = {
        "summary": summary,
        "semantics": semantics,
    }
    if hasattr(entity, "project_id"):
        meta["project_id"] = str(getattr(entity, "project_id"))
    return GraphNode(
        id=entity.id,
        type=entity_type,
        label=_entity_label(entity),
        meta=meta,
    )


def _sort_nodes(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    return sorted(
        nodes,
        key=lambda node: (
            _TYPE_ORDER.get(node.type, 99),
            (node.meta or {}).get("summary") or node.label or "",
            str(node.id),
        ),
    )


async def _walk_direction(
    session: AsyncSession,
    *,
    start_type: str,
    start_id: uuid.UUID,
    project_id: uuid.UUID,
    direction: str,
    max_depth: int,
    max_nodes: int,
    max_edges: int,
    type_limits: dict[str, int],
) -> tuple[list[GraphNode], list[GraphEdge], bool]:
    visited: set[tuple[str, uuid.UUID]] = set()
    nodes: dict[tuple[str, uuid.UUID], GraphNode] = {}
    edges: list[GraphEdge] = []
    frontier: list[tuple[str, uuid.UUID, int]] = [(start_type, start_id, 0)]
    type_counts: dict[str, int] = {}
    truncated = False

    while frontier:
        current_type, current_id, depth = frontier.pop(0)
        if depth >= max_depth:
            continue

        stmt = select(Trace).where(
            Trace.project_id == project_id,
            Trace.deleted_at.is_(None),
        )
        if direction == "backward":
            stmt = stmt.where(Trace.to_type == current_type, Trace.to_id == current_id)
        else:
            stmt = stmt.where(Trace.from_type == current_type, Trace.from_id == current_id)
        stmt = stmt.order_by(Trace.generated_at.desc(), Trace.id.desc())

        traces = (await session.execute(stmt)).scalars().all()
        for trace in traces:
            neighbor_type = trace.from_type if direction == "backward" else trace.to_type
            neighbor_id = trace.from_id if direction == "backward" else trace.to_id
            key = (neighbor_type, neighbor_id)
            entity = await load_entity(session, neighbor_type, neighbor_id)
            if not entity:
                continue
            entity_project_id = getattr(entity, "project_id", None)
            if neighbor_type == "project":
                entity_project_id = entity.id
            if entity_project_id and entity_project_id != project_id:
                continue

            if len(edges) >= max_edges:
                truncated = True
                continue

            if key not in nodes:
                if len(nodes) >= max_nodes:
                    truncated = True
                    continue
                type_limit = type_limits.get(neighbor_type)
                current_count = type_counts.get(neighbor_type, 0)
                if type_limit is not None and current_count >= type_limit:
                    truncated = True
                    continue
                nodes[key] = _to_graph_node(neighbor_type, entity)
                type_counts[neighbor_type] = current_count + 1
            edges.append(
                GraphEdge(
                    from_id=trace.from_id,
                    to_id=trace.to_id,
                    relation_type=trace.relation_type,
                    relation_strength=trace.relation_strength,
                    depth=depth + 1,
                    direction=direction,
                )
            )
            if key not in visited:
                visited.add(key)
                frontier.append((neighbor_type, neighbor_id, depth + 1))

    return _sort_nodes(nodes.values()), edges, truncated


async def _project_brief(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    max_documents: int,
    max_tasks: int,
    max_artifacts: int,
) -> dict[str, list[GraphNode]]:
    docs = (
        await session.execute(
            select(Document)
            .where(Document.project_id == project_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
            .limit(max_documents)
        )
    ).scalars().all()
    tasks = (
        await session.execute(
            select(Task)
            .where(Task.project_id == project_id, Task.deleted_at.is_(None))
            .order_by(Task.created_at.desc())
            .limit(max_tasks)
        )
    ).scalars().all()
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.deleted_at.is_(None))
            .order_by(Artifact.created_at.desc())
            .limit(max_artifacts)
        )
    ).scalars().all()
    return {
        "documents": [_to_graph_node("document", doc) for doc in docs],
        "tasks": [_to_graph_node("task", task) for task in tasks],
        "artifacts": [_to_graph_node("artifact", artifact) for artifact in artifacts],
    }


def _resolved_limits(
    *,
    max_depth: int | None = None,
    base: GraphContextLimits = DEFAULT_CONTEXT_LIMITS,
) -> GraphContextLimits:
    return GraphContextLimits(
        max_depth=max(1, min(max_depth or base.max_depth, 6)),
        max_ancestor_nodes=base.max_ancestor_nodes,
        max_descendant_nodes=base.max_descendant_nodes,
        max_edges=base.max_edges,
        max_documents=base.max_documents,
        max_tasks=base.max_tasks,
        max_artifacts=base.max_artifacts,
        max_runs=base.max_runs,
        max_work_items=base.max_work_items,
    )


def _type_limits(limits: GraphContextLimits) -> dict[str, int]:
    return {
        "document": limits.max_documents,
        "task": limits.max_tasks,
        "artifact": limits.max_artifacts,
        "run": limits.max_runs,
        "work_item": limits.max_work_items,
    }


async def build_graph_context(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    max_depth: int = 4,
    limits: GraphContextLimits | None = None,
) -> GraphContextResponse:
    root_entity = await load_entity(session, entity_type, entity_id)
    if not root_entity:
        raise ValueError("Entity not found")

    effective_project_id = project_id or getattr(root_entity, "project_id", None) or getattr(root_entity, "id", None)
    if effective_project_id is None:
        raise ValueError("Unable to determine project scope")

    window = _resolved_limits(max_depth=max_depth, base=limits or DEFAULT_CONTEXT_LIMITS)
    root = _to_graph_node(entity_type, root_entity)
    ancestors, ancestor_edges, ancestor_truncated = await _walk_direction(
        session,
        start_type=entity_type,
        start_id=entity_id,
        project_id=effective_project_id,
        direction="backward",
        max_depth=window.max_depth,
        max_nodes=window.max_ancestor_nodes,
        max_edges=window.max_edges,
        type_limits=_type_limits(window),
    )
    descendants, descendant_edges, descendant_truncated = await _walk_direction(
        session,
        start_type=entity_type,
        start_id=entity_id,
        project_id=effective_project_id,
        direction="forward",
        max_depth=2,
        max_nodes=window.max_descendant_nodes,
        max_edges=max(1, window.max_edges // 2),
        type_limits=_type_limits(window),
    )
    edges = ancestor_edges + descendant_edges
    project_brief = await _project_brief(
        session,
        effective_project_id,
        max_documents=window.max_documents,
        max_tasks=window.max_tasks,
        max_artifacts=window.max_artifacts,
    )
    return GraphContextResponse(
        root=root,
        ancestors=ancestors,
        descendants=descendants,
        edges=edges,
        project_brief=project_brief,
        budget=GraphContextBudget(
            **asdict(window),
            truncated=ancestor_truncated or descendant_truncated,
            returned_counts={
                "ancestors": len(ancestors),
                "descendants": len(descendants),
                "edges": len(edges),
                "documents": len(project_brief["documents"]),
                "tasks": len(project_brief["tasks"]),
                "artifacts": len(project_brief["artifacts"]),
            },
        ),
    )


def compact_graph_context(context: GraphContextResponse) -> dict[str, Any]:
    def slim(node: GraphNode) -> dict[str, Any]:
        meta = node.meta or {}
        return {
            "id": str(node.id),
            "type": node.type,
            "label": node.label,
            "summary": meta.get("summary"),
            "semantics": meta.get("semantics") or {},
        }

    lineage: dict[str, dict[str, Any]] = {"root": slim(context.root)}
    for node in context.ancestors:
        lineage.setdefault(node.type, slim(node))

    return {
        "root": slim(context.root),
        "lineage": lineage,
        "ancestors": [slim(node) for node in context.ancestors],
        "descendants": [slim(node) for node in context.descendants],
        "project_brief": {
            group: [slim(node) for node in nodes]
            for group, nodes in context.project_brief.items()
        },
        "budget": context.budget.model_dump(mode="json"),
    }
