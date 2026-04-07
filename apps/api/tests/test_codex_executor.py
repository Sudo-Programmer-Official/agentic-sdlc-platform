from app.runtime.codex_executor import _verification_from_action_scope
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
