from __future__ import annotations

from typing import List

from core.models import (
    QualityType,
    RequirementEdge,
    RequirementGraph,
    RequirementNode,
    RequirementType,
    RequirementGraphStatus,
)


KEYWORD_TO_QUALITY = {
    "performance": QualityType.PERFORMANCE,
    "secure": QualityType.SECURITY,
    "security": QualityType.SECURITY,
    "reliable": QualityType.RELIABILITY,
    "reliability": QualityType.RELIABILITY,
    "scalable": QualityType.SCALABILITY,
    "scalability": QualityType.SCALABILITY,
    "available": QualityType.AVAILABILITY,
    "availability": QualityType.AVAILABILITY,
    "privacy": QualityType.PRIVACY,
    "compliance": QualityType.COMPLIANCE,
    "cost": QualityType.COST,
    "maintain": QualityType.MAINTAINABILITY,
}


def extract_graph_from_prd(text: str) -> RequirementGraph:
    """
    Deterministic heuristic extractor:
    - Lines starting with Must/Should/Allow -> FR
    - Lines containing quality keywords -> QR
    - Edges connect each FR to each QR for demo visibility
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fr_nodes: List[RequirementNode] = []
    qr_nodes: List[RequirementNode] = []

    fr_count = 0
    qr_count = 0

    for line in lines:
        lower = line.lower()
        quality_type = _match_quality(lower)
        if line.startswith(("Must", "Should", "Allow", "must", "should", "allow")):
            fr_count += 1
            fr_nodes.append(
                RequirementNode(
                    id=f"FR-{fr_count:03d}",
                    type=RequirementType.FR,
                    text=line,
                    confidence=0.9,
                    source="AI_EXTRACTED",
                )
            )
        if quality_type:
            qr_count += 1
            qr_nodes.append(
                RequirementNode(
                    id=f"QR-{qr_count:03d}",
                    type=RequirementType.QR,
                    text=line,
                    confidence=0.9,
                    source="AI_EXTRACTED",
                    quality_type=quality_type,
                )
            )

    # Fallback defaults so UI has content
    if not fr_nodes:
        fr_nodes.append(
            RequirementNode(
                id="FR-001",
                type=RequirementType.FR,
                text="System must support core user flow.",
                confidence=0.7,
                source="AI_EXTRACTED",
            )
        )
    if not qr_nodes:
        qr_nodes.append(
            RequirementNode(
                id="QR-001",
                type=RequirementType.QR,
                text="System should be reliable and secure.",
                confidence=0.7,
                source="AI_EXTRACTED",
                quality_type=QualityType.RELIABILITY,
            )
        )

    edges: List[RequirementEdge] = []
    edge_count = 0
    for fr in fr_nodes:
        for qr in qr_nodes:
            edge_count += 1
            edges.append(
                RequirementEdge(
                    id=f"EDGE-{edge_count:03d}",
                    from_id=fr.id,
                    to_id=qr.id,
                    relation="constrains",
                    weight=0.5,
                )
            )

    return RequirementGraph(
        project_id="",
        version=1,
        nodes=[*fr_nodes, *qr_nodes],
        edges=edges,
        status=RequirementGraphStatus.DRAFT,
    )


def _match_quality(text: str):
    for keyword, quality in KEYWORD_TO_QUALITY.items():
        if keyword in text:
            return quality
    return None
