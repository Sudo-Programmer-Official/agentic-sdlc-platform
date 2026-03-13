from __future__ import annotations

from app.runtime.execution_graph_spec import current_work_item_stage_map, get_execution_graph_spec


def test_execution_graph_spec_is_well_formed():
    spec = get_execution_graph_spec()
    node_ids = [node.id for node in spec.nodes]

    assert len(node_ids) == len(set(node_ids))
    assert [node.id for node in spec.nodes if node.lane == "mutating"] == ["APPLY_PATCH"]

    valid_nodes = set(node_ids)
    for edge in spec.edges:
        assert edge.source in valid_nodes
        assert edge.target in valid_nodes

    for skip_rule in spec.skip_rules:
        assert skip_rule.skip_nodes
        for node_id in skip_rule.skip_nodes:
            assert node_id in valid_nodes

    for retry_rule in spec.retry_rules:
        assert retry_rule.node_id in valid_nodes
        assert retry_rule.max_retries >= 0


def test_current_work_item_types_map_to_expected_execution_nodes():
    mapping = current_work_item_stage_map()

    assert mapping["PLAN_DAG"] == "PLAN"
    assert mapping["CODE_BACKEND"] == "APPLY_PATCH"
    assert mapping["CODE_FRONTEND"] == "APPLY_PATCH"
    assert mapping["REVIEW_DIFF"] == "PATCH_VERIFY"
    assert mapping["WRITE_TESTS"] == "RUN_UNIT_TESTS"
    assert mapping["RUN_TESTS"] == "RUN_UNIT_TESTS"
    assert mapping["FIX_TEST_FAILURE"] == "RUN_UNIT_TESTS"
    assert mapping["REVIEW_INTEGRATION"] == "VALIDATE_RESULTS"
