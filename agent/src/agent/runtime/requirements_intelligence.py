from __future__ import annotations

import re
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

_STRUCTURED_REQ_RE = re.compile(
    r"^(?P<prefix>FR|QR)\s*[-_ ]?(?P<index>[A-Za-z0-9_-]+)?\s*(?::|-|\.)\s*(?P<text>.+)$",
    re.IGNORECASE,
)
_LEADING_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def _clean_requirement_line(line: str) -> str:
    return _LEADING_BULLET_RE.sub("", line.strip())


def _normalize_requirement_id(prefix: str, raw_index: str | None, fallback_index: int) -> str:
    normalized_prefix = prefix.upper()
    if raw_index:
        cleaned = raw_index.strip().upper().replace("_", "-")
        if cleaned.isdigit():
            return f"{normalized_prefix}-{int(cleaned):03d}"
        return f"{normalized_prefix}-{cleaned}"
    return f"{normalized_prefix}-{fallback_index:03d}"


def extract_graph_from_prd(text: str) -> RequirementGraph:
    """
    Deterministic heuristic extractor:
    - Lines starting with Must/Should/Allow -> FR
    - Lines containing quality keywords -> QR
    - Edges connect each FR to each QR for demo visibility
    """
    lines = [_clean_requirement_line(line) for line in text.splitlines() if line.strip()]
    fr_nodes: List[RequirementNode] = []
    qr_nodes: List[RequirementNode] = []

    fr_count = 0
    qr_count = 0

    for line in lines:
        structured_match = _STRUCTURED_REQ_RE.match(line)
        if structured_match:
            prefix = structured_match.group("prefix").upper()
            raw_index = structured_match.group("index")
            requirement_text = structured_match.group("text").strip()
            if not requirement_text:
                continue
            if prefix == "FR":
                fr_count += 1
                fr_nodes.append(
                    RequirementNode(
                        id=_normalize_requirement_id(prefix, raw_index, fr_count),
                        type=RequirementType.FR,
                        text=requirement_text,
                        confidence=0.95,
                        source="AI_EXTRACTED",
                    )
                )
            else:
                qr_count += 1
                qr_nodes.append(
                    RequirementNode(
                        id=_normalize_requirement_id(prefix, raw_index, qr_count),
                        type=RequirementType.QR,
                        text=requirement_text,
                        confidence=0.95,
                        source="AI_EXTRACTED",
                        quality_type=_match_quality(requirement_text.lower()),
                    )
                )
            continue

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

    # Fallback defaults only when the input produced no usable requirements at all.
    if not fr_nodes and not qr_nodes:
        fr_nodes.append(
            RequirementNode(
                id="FR-001",
                type=RequirementType.FR,
                text="System must support core user flow.",
                confidence=0.7,
                source="AI_EXTRACTED",
            )
        )
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
