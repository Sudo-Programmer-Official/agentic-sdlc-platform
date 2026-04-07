from types import SimpleNamespace

from app.runtime.codex_executor import (
    _edit_budget_from_payload,
    _is_static_frontend_scope,
    _stage_scope_violations,
    _target_files_from_payload,
    _verification_from_action_scope,
    CodexExecutor,
)
from app.schemas.run_narrative import RunPatchVerificationFinding, RunPatchVerificationSummary


def _no_scope_verification() -> RunPatchVerificationSummary:
    return RunPatchVerificationSummary(
        status="NO_SCOPE",
        requires_confirmation=True,
        risk_level="LOW",
        file_count=0,
        max_files=5,
        findings=[
            RunPatchVerificationFinding(
                code="no_scope",
                severity="warning",
                title="No planned patch files identified yet",
                detail="The system can describe the run, but it does not yet have a bounded patch file envelope for this run.",
                files=[],
            )
        ],
        suggested_next_action="Require operator confirmation before patch execution.",
    )


def test_verification_from_action_scope_unblocks_bounded_plan_actions():
    verification = _verification_from_action_scope(
        _no_scope_verification(),
        ["hello_world.py", "test_hello_world.py"],
    )

    assert verification is not None
    assert verification.status == "READY"
    assert verification.requires_confirmation is False
    assert verification.file_count == 2
    assert verification.verified_files == ["hello_world.py", "test_hello_world.py"]
    assert verification.actual_files == ["hello_world.py", "test_hello_world.py"]
    assert verification.scope_match is True
    assert verification.suggested_next_action == "Proceed with the bounded patch and validation sequence."
    assert [finding.code for finding in verification.findings] == ["scope_from_actions"]


def test_verification_from_action_scope_keeps_confirmation_for_sensitive_paths():
    verification = _verification_from_action_scope(
        _no_scope_verification(),
        ["app/auth.py"],
    )

    assert verification is not None
    assert verification.status == "REQUIRES_CONFIRMATION"
    assert verification.requires_confirmation is True
    assert verification.file_count == 1
    assert verification.verified_files == ["app/auth.py"]
    assert verification.actual_files == ["app/auth.py"]
    assert verification.scope_match is True
    assert verification.suggested_next_action == "Require operator confirmation before patch execution."
    assert [finding.code for finding in verification.findings] == ["scope_from_actions"]


def test_target_files_from_payload_prefers_explicit_target_scope():
    target_files = _target_files_from_payload(
        {
            "target_files": ["index.html", "styles.css"],
            "files": ["README.md"],
        }
    )

    assert target_files == ["index.html", "styles.css"]


def test_target_files_from_payload_falls_back_to_expected_files():
    target_files = _target_files_from_payload(
        {
            "expected_files": ["index.html"],
        }
    )

    assert target_files == ["index.html"]


def test_edit_budget_from_payload_uses_minimal_patch_limits():
    edit_budget = _edit_budget_from_payload(
        {
            "edit_budget": {
                "mode": "minimal_patch",
                "max_files": 2,
                "hard_max_files": 4,
            }
        }
    )

    assert edit_budget == {
        "mode": "minimal_patch",
        "file_budget": 2,
        "hard_file_budget": 4,
    }


def test_static_frontend_scope_detects_html_css_only_targets():
    assert _is_static_frontend_scope({"expected_files": ["index.html", "styles.css"]}) is True
    assert _is_static_frontend_scope({"expected_files": ["index.html", "hero.py"]}) is False


def test_instructions_for_write_tests_discourage_new_third_party_dependencies():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "Restrict edits to these files unless validation proves a neighboring file is required: index.html." in instructions
    assert "This is a static frontend task." in instructions
    assert "Do not introduce new third-party imports such as BeautifulSoup or bs4" in instructions
    assert "html.parser" in instructions


def test_write_tests_stage_rejects_non_test_file_mutations():
    work_item = SimpleNamespace(type="WRITE_TESTS")

    violations = _stage_scope_violations(work_item, ["index.html", "test_index_html.py"])

    assert violations == [
        "WRITE_TESTS may only modify Python test files; received out-of-scope file index.html."
    ]
