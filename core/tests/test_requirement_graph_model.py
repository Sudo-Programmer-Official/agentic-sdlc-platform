from core.models import (
    RequirementEdge,
    RequirementGraph,
    RequirementGraphStatus,
    RequirementNode,
    RequirementType,
    QualityType,
)


def test_requirement_graph_hash_is_order_insensitive():
    nodes = [
        RequirementNode(
            id="FR-001",
            type=RequirementType.FR,
            text="System shall allow login",
            confidence=0.9,
            source="test",
            quality_type=None,
        ),
        RequirementNode(
            id="QR-001",
            type=RequirementType.QR,
            text="System shall be secure",
            confidence=0.9,
            source="test",
            quality_type=QualityType.SECURITY,
        ),
    ]
    edges = [
        RequirementEdge(
            id="EDGE-001",
            from_id="FR-001",
            to_id="QR-001",
            relation="constrains",
            weight=0.8,
            rationale=None,
        )
    ]

    graph_a = RequirementGraph(
        project_id="p1",
        version=1,
        nodes=nodes,
        edges=edges,
        status=RequirementGraphStatus.DRAFT,
    )
    # Reverse order to ensure deterministic hashing
    graph_b = RequirementGraph(
        project_id="p1",
        version=1,
        nodes=list(reversed(nodes)),
        edges=list(reversed(edges)),
        status=RequirementGraphStatus.DRAFT,
    )

    assert graph_a.compute_hash() == graph_b.compute_hash()
