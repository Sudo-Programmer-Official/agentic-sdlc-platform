from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4
from pathlib import Path
import json

from core.ledger import ActionLedger
from core.models import (
    Project,
    RequirementEdge,
    RequirementGraph,
    RequirementGraphSnapshot,
    RequirementGraphStatus,
    RequirementNode,
    RequirementType,
    QualityType,
    Stage,
)

from .errors import (
    RequirementGraphNotApprovedError,
    RequirementGraphNotFoundError,
    RequirementGraphStaleError,
)


class InMemoryRequirementGraphStore:
    def __init__(self) -> None:
        self._graphs: Dict[str, RequirementGraph] = {}
        self._snapshots: Dict[str, List[RequirementGraphSnapshot]] = {}

    def get(self, project_id: str) -> RequirementGraph:
        graph = self._graphs.get(project_id)
        if graph is None:
            raise RequirementGraphNotFoundError(f"Requirements graph for {project_id} not found")
        return graph

    def upsert(self, graph: RequirementGraph) -> None:
        self._graphs[graph.project_id] = graph

    def add_snapshot(self, snapshot: RequirementGraphSnapshot) -> None:
        self._snapshots.setdefault(snapshot.project_id, []).append(snapshot)

    def latest_version(self, project_id: str) -> int:
        graph = self._graphs.get(project_id)
        return graph.version if graph else 0


class RequirementGraphService:
    def __init__(
        self,
        store: InMemoryRequirementGraphStore,
        ledger: ActionLedger,
        project_getter,
        project_updater,
        extractor,
        docs_root: Optional[Path] = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._project_getter = project_getter
        self._project_updater = project_updater
        self._extractor = extractor
        self._docs_root = docs_root or Path(__file__).resolve().parents[4] / "docs"

    # ----- Public API -----
    def ingest_prd(self, project_id: str, text: str, source: str = "typed", fmt: str = "markdown") -> RequirementGraph:
        self._project_getter(project_id)
        version = self._store.latest_version(project_id) + 1
        graph = self._extractor(text)
        graph.project_id = project_id
        graph.version = version
        graph.status = RequirementGraphStatus.DRAFT
        graph.created_at = datetime.utcnow()
        graph.updated_at = graph.created_at
        graph.approved_at = None
        graph.approved_by = None
        self._store.upsert(graph)
        self._ledger.log(
            run_id="system",
            project_id=project_id,
            stage=Stage.REQUIREMENTS_DRAFTED,
            agent_name="system",
            tool_name="requirements_service",
            message="Requirements graph created from PRD",
            details={"version": version, "source": source, "format": fmt},
        )
        return graph

    def get_graph(self, project_id: str) -> RequirementGraph:
        return self._store.get(project_id)

    def update_graph(self, project_id: str, nodes: List[RequirementNode], edges: List[RequirementEdge]) -> RequirementGraph:
        existing = self._store.get(project_id)
        new_version = existing.version + 1
        status = RequirementGraphStatus.STALE if existing.status == RequirementGraphStatus.APPROVED else RequirementGraphStatus.DRAFT
        updated = RequirementGraph(
            project_id=project_id,
            version=new_version,
            nodes=nodes,
            edges=edges,
            status=status,
            created_at=existing.created_at,
            updated_at=datetime.utcnow(),
            approved_at=None if status != RequirementGraphStatus.APPROVED else existing.approved_at,
            approved_by=None if status != RequirementGraphStatus.APPROVED else existing.approved_by,
        )
        self._store.upsert(updated)
        self._apply_propagation_flags(project_id, existing, updated)
        self._ledger.log(
            run_id="system",
            project_id=project_id,
            stage=Stage.REQUIREMENTS_DRAFTED,
            agent_name="system",
            tool_name="requirements_service",
            message="Requirements graph updated",
            details={
                "from_version": existing.version,
                "to_version": new_version,
                "status": updated.status.value,
            },
        )
        if status == RequirementGraphStatus.STALE:
            self._ledger.log(
                run_id="system",
                project_id=project_id,
                stage=Stage.REQUIREMENTS_DRAFTED,
                agent_name="system",
                tool_name="requirements_service",
                message="Requirements graph marked stale after update",
                details={"version": new_version},
            )
        return updated

    def approve_graph(self, project_id: str, approved_by: str) -> RequirementGraphSnapshot:
        graph = self._store.get(project_id)
        graph.status = RequirementGraphStatus.APPROVED
        graph.approved_at = datetime.utcnow()
        graph.approved_by = approved_by
        graph.updated_at = graph.approved_at
        self._store.upsert(graph)

        sha = graph.compute_hash()
        snapshot = RequirementGraphSnapshot(
            project_id=project_id,
            graph_version=graph.version,
            sha256=sha,
            created_by=approved_by or "system",
        )
        self._store.add_snapshot(snapshot)
        self._write_graph_to_docs(graph, sha)
        self._ledger.log(
            run_id="system",
            project_id=project_id,
            stage=Stage.REQUIREMENTS_DRAFTED,
            agent_name="system",
            tool_name="requirements_service",
            message="Requirements graph approved",
            details={"version": graph.version, "sha": sha},
        )
        # Reset propagation flags on approval
        self._project_updater(project_id, architecture=False, plan=False, tests=False)
        return snapshot

    def assert_approved(self, project_id: str) -> None:
        graph = self._store.get(project_id)
        if graph.status != RequirementGraphStatus.APPROVED:
            raise RequirementGraphNotApprovedError("Requirements graph not approved")

    def assert_fresh(self, project_id: str) -> None:
        graph = self._store.get(project_id)
        if graph.status == RequirementGraphStatus.STALE:
            raise RequirementGraphStaleError("Requirements graph changed since approval.")

    # ----- Helpers -----
    def _apply_propagation_flags(
        self,
        project_id: str,
        previous: RequirementGraph,
        updated: RequirementGraph,
    ) -> None:
        fr_changed = self._nodes_changed(previous, updated, RequirementType.FR)
        qr_changed = self._nodes_changed(previous, updated, RequirementType.QR)
        edges_changed = self._edges_changed(previous, updated)

        arch = qr_changed
        plan = qr_changed or fr_changed or edges_changed
        tests = qr_changed or fr_changed

        if any([arch, plan, tests]):
            self._project_updater(project_id, architecture=arch, plan=plan, tests=tests)
            self._ledger.log(
                run_id="system",
                project_id=project_id,
                stage=Stage.REQUIREMENTS_DRAFTED,
                agent_name="system",
                tool_name="requirements_service",
                message="Propagation flags updated",
                details={"architecture": arch, "plan": plan, "tests": tests},
            )

    @staticmethod
    def _nodes_changed(prev: RequirementGraph, new: RequirementGraph, rtype: RequirementType) -> bool:
        prev_nodes = {n.id: n for n in prev.nodes if n.type == rtype}
        new_nodes = {n.id: n for n in new.nodes if n.type == rtype}
        if prev_nodes.keys() != new_nodes.keys():
            return True
        for node_id, node in prev_nodes.items():
            new_node = new_nodes[node_id]
            if (
                node.text != new_node.text
                or node.quality_type != new_node.quality_type
                or node.confidence != new_node.confidence
                or node.source != new_node.source
                or set(node.tags) != set(new_node.tags)
            ):
                return True
        return False

    @staticmethod
    def _edges_changed(prev: RequirementGraph, new: RequirementGraph) -> bool:
        prev_edges = {(e.id, e.from_id, e.to_id, e.relation, e.weight, e.rationale) for e in prev.edges}
        new_edges = {(e.id, e.from_id, e.to_id, e.relation, e.weight, e.rationale) for e in new.edges}
        return prev_edges != new_edges

    def _write_graph_to_docs(self, graph: RequirementGraph, sha: str) -> None:
        try:
            self._docs_root.mkdir(parents=True, exist_ok=True)
            out = self._docs_root / "REQUIREMENTS_GRAPH.json"
            serializable = graph_to_dict(graph) | {"sha256": sha}
            # isoformat datetime fields
            for key in ("created_at", "updated_at", "approved_at"):
                if serializable.get(key):
                    serializable[key] = serializable[key].isoformat()
            out.write_text(json.dumps(serializable, indent=2))
        except Exception:
            # Silent failure to avoid blocking approval; ledger already recorded approval
            return


# Utility helpers for converting input DTOs to domain nodes/edges
def build_nodes(raw_nodes: List[dict]) -> List[RequirementNode]:
    nodes: List[RequirementNode] = []
    for entry in raw_nodes:
        quality_val = entry.get("quality_type")
        if quality_val:
            quality_val = quality_val.value if hasattr(quality_val, "value") else str(quality_val)
        nodes.append(
            RequirementNode(
                id=entry["id"],
                type=RequirementType(entry["type"]),
                text=entry["text"],
                confidence=entry.get("confidence", 0.8),
                source=entry.get("source", "human"),
                quality_type=QualityType(quality_val) if quality_val else None,
                tags=entry.get("tags", []) or [],
            )
        )
    return nodes


def build_edges(raw_edges: List[dict]) -> List[RequirementEdge]:
    edges: List[RequirementEdge] = []
    for entry in raw_edges:
        edges.append(
            RequirementEdge(
                id=entry.get("id") or str(uuid4()),
                from_id=entry["from_id"],
                to_id=entry["to_id"],
                relation=entry.get("relation", "constrains"),
                weight=float(entry.get("weight", 0.5)),
                rationale=entry.get("rationale"),
            )
        )
    return edges


def graph_to_dict(graph: RequirementGraph) -> dict:
    return {
        "project_id": graph.project_id,
        "version": graph.version,
        "status": graph.status.value,
        "created_at": graph.created_at,
        "updated_at": graph.updated_at,
        "approved_at": graph.approved_at,
        "approved_by": graph.approved_by,
        "nodes": [
            {
                "id": node.id,
                "type": node.type.value,
                "text": node.text,
                "confidence": node.confidence,
                "source": node.source,
                "quality_type": node.quality_type.value if node.quality_type else None,
                "tags": list(node.tags),
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "from_id": edge.from_id,
                "to_id": edge.to_id,
                "relation": edge.relation,
                "weight": edge.weight,
                "rationale": edge.rationale,
            }
            for edge in graph.edges
        ],
    }
