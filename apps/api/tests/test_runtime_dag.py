from app.runtime.dag import _task_payload_from_summary


def test_task_payload_from_summary_carries_target_scope_and_budget():
    payload = _task_payload_from_summary(
        {
            "task_id": "task-123",
            "task_title": "Improve homepage layout",
            "goal": "Improve homepage layout",
            "target_files": ["index.html", "styles.css"],
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            },
        }
    )

    assert payload["target_files"] == ["index.html", "styles.css"]
    assert payload["files"] == ["index.html", "styles.css"]
    assert payload["expected_files"] == ["index.html", "styles.css"]
    assert payload["edit_budget"] == {
        "mode": "minimal_patch",
        "max_files": 2,
        "hard_max_files": 4,
    }
