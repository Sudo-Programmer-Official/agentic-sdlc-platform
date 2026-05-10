from app.services.knowledge_service import _change_type_from_paths, _impact_flags, _risk_level, _truncate_varchar


def test_change_type_heuristics_identify_schema_changes():
    paths = ["apps/api/alembic/versions/20260314_add_table.py", "apps/api/app/db/models/knowledge.py"]
    change_type = _change_type_from_paths(paths, "Add knowledge tables", "")
    flags = _impact_flags(paths, ["apps/api"])

    assert change_type == "schema"
    assert flags["impacts_schema"] is True
    assert _risk_level(change_type, flags, len(paths)) == "high"


def test_change_type_heuristics_identify_test_only_low_signal_changes():
    paths = ["apps/api/tests/test_knowledge_api.py", "apps/api/tests/test_runtime_flow.py"]
    change_type = _change_type_from_paths(paths, "Tighten tests", "")
    flags = _impact_flags(paths, ["apps/api"])

    assert change_type == "test"
    assert flags["docs_only"] is False
    assert flags["test_only"] is True
    assert _risk_level(change_type, flags, len(paths)) == "low"


def test_truncate_varchar_caps_and_normalizes_blank():
    assert _truncate_varchar("  hello  ", 10) == "hello"
    assert _truncate_varchar("x" * 300, 255) == ("x" * 255)
    assert _truncate_varchar("   ", 10) is None
