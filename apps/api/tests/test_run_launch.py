import uuid

from app.db.models import Task
from app.services.run_launch import _build_task_run_summary, _default_runtime_governance_mode, _resolve_runtime_governance_mode


def test_build_task_run_summary_carries_task_result_scope_metadata():
    task = Task(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="Implement hero section",
        description="Add a hero section to the homepage.",
        source="ai",
        branch_strategy="auto",
        result_payload={
            "expected_files": ["index.html"],
            "target_files": ["index.html"],
            "related_files": ["index.html"],
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            },
        },
    )

    summary = _build_task_run_summary(task)

    assert summary["goal"] == "Implement hero section: Add a hero section to the homepage."
    assert summary["expected_files"] == ["index.html"]
    assert summary["target_files"] == ["index.html"]
    assert summary["related_files"] == ["index.html"]
    assert summary["edit_budget"] == {
        "mode": "minimal_patch",
        "max_files": 2,
        "hard_max_files": 4,
    }


def test_default_runtime_governance_mode_defaults_stability_for_early_states():
    assert _default_runtime_governance_mode("GENESIS") == "stability"
    assert _default_runtime_governance_mode("EARLY_BUILD") == "stability"
    assert _default_runtime_governance_mode("ACTIVE_PRODUCT") == "stability"


def test_resolve_runtime_governance_mode_defaults_active_product_to_stability():
    assert _resolve_runtime_governance_mode(repository_state="GENESIS", has_preview_success=False) == "stability"
    assert _resolve_runtime_governance_mode(repository_state="EARLY_BUILD", has_preview_success=False) == "stability"
    assert _resolve_runtime_governance_mode(repository_state="ACTIVE_PRODUCT", has_preview_success=False) == "stability"
    assert _resolve_runtime_governance_mode(repository_state="ACTIVE_PRODUCT", has_preview_success=True) == "stability"
    assert (
        _resolve_runtime_governance_mode(
            repository_state="ACTIVE_PRODUCT",
            has_preview_success=True,
            active_product_default_mode="governed",
        )
        == "governed"
    )
    assert (
        _resolve_runtime_governance_mode(
            repository_state="ACTIVE_PRODUCT",
            has_preview_success=True,
            active_product_default_mode="stability",
            emergency_ship_mode_enabled=True,
        )
        == "emergency"
    )
