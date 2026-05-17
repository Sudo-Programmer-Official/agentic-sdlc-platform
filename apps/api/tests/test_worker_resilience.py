import asyncio
from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from app.runtime.recovery_policy import classify_failure, plan_recovery
from app.runtime.recovery_policy import _next_same_signature_count
from app.runtime.runtime_recovery_service import RuntimeRecoveryService
from app.runtime.orchestrator import _design_governance_violation_payload as orchestrator_design_payload
from app.runtime.worker_service import (
    _degraded_backoff_seconds,
    _design_governance_violation_payload as worker_design_payload,
    _is_transient_worker_error,
)


def test_worker_transient_error_classifier():
    assert _is_transient_worker_error(TimeoutError("timed out"))
    assert _is_transient_worker_error(asyncio.TimeoutError("timeout"))
    assert _is_transient_worker_error(ConnectionError("connection reset by peer"))
    assert _is_transient_worker_error(OperationalError("select 1", {}, Exception("connection refused")))
    assert not _is_transient_worker_error(ValueError("invalid task payload"))


def test_worker_transient_backoff_is_bounded():
    assert _degraded_backoff_seconds(1) == 1.0
    assert _degraded_backoff_seconds(2) == 2.0
    assert _degraded_backoff_seconds(3) == 4.0
    assert _degraded_backoff_seconds(4) == 8.0
    assert _degraded_backoff_seconds(50) == 8.0


def test_design_governance_payload_detects_warning_and_records():
    result = {
        "warnings": ["patch_guard_violation", "design_contract_violation"],
        "patch_guard": {
            "project_enforcement_mode": "strict",
            "design_violation_records": [
                {"type": "design_contract_violation", "rule": "allowed_components", "file": "apps/web/src/page.tsx"}
            ],
            "project_violation_records": [
                {"type": "design_contract_violation", "rule": "enforce_color_tokens", "file": "apps/web/src/page.tsx"}
            ],
        },
    }

    worker_payload = worker_design_payload(result)
    orchestrator_payload = orchestrator_design_payload(result)

    assert worker_payload is not None
    assert orchestrator_payload is not None
    assert worker_payload["reason"] == "design_contract_violation"
    assert orchestrator_payload["reason"] == "design_contract_violation"
    assert worker_payload["project_enforcement_mode"] == "strict"
    assert orchestrator_payload["project_enforcement_mode"] == "strict"


def test_design_governance_payload_returns_none_without_signal():
    result = {
        "warnings": ["patch_guard_violation"],
        "patch_guard": {
            "project_enforcement_mode": "warn",
            "design_violation_records": [],
            "project_violation_records": [{"type": "project_contract_violation", "rule": "unknown"}],
        },
    }

    assert worker_design_payload(result) is None
    assert orchestrator_design_payload(result) is None


def test_recovery_classifies_design_token_and_patch_size_violations():
    token_violation = SimpleNamespace(
        type="CODE_FRONTEND",
        status="FAILED",
        executor="codex",
        last_error="Design contract violation in index.html: ad-hoc hex color #ec4899 is not in token_registry.colors.",
        result={},
    )
    patch_size_violation = SimpleNamespace(
        type="CODE_BACKEND",
        status="FAILED",
        executor="codex",
        last_error="Action error: Patch too large for app.py (>40% change)",
        result={},
    )
    assert classify_failure(token_violation) == "design_token_violation"
    assert classify_failure(patch_size_violation) == "patch_size_violation"


def test_recovery_classifies_model_call_failed_as_transient():
    model_failure = SimpleNamespace(
        type="CODE_BACKEND",
        status="FAILED",
        executor="codex",
        last_error="AI policy halted execution: model_call_failed",
        result={},
    )
    assert classify_failure(model_failure) == "transient"


def test_recovery_classifies_output_contract_invalid_policy_halt_correctly():
    output_contract_failure = SimpleNamespace(
        type="CODE_FRONTEND",
        status="FAILED",
        executor="codex",
        last_error="AI policy halted execution: output_contract_invalid",
        result={},
    )
    assert classify_failure(output_contract_failure) == "output_contract_invalid"


def test_frontend_design_token_violation_has_retry_recovery_rule():
    work_item = SimpleNamespace(type="CODE_FRONTEND", status="FAILED")
    rule = plan_recovery(work_item, "design_token_violation")
    assert rule is not None
    assert rule.action == "retry"


def test_backend_patch_size_violation_has_retry_recovery_rule():
    work_item = SimpleNamespace(type="CODE_BACKEND", status="FAILED")
    rule = plan_recovery(work_item, "patch_size_violation")
    assert rule is not None
    assert rule.action == "retry"


def test_backend_output_contract_invalid_has_retry_recovery_rule():
    work_item = SimpleNamespace(type="CODE_BACKEND", status="FAILED")
    rule = plan_recovery(work_item, "output_contract_invalid")
    assert rule is not None
    assert rule.action == "retry"


def test_recovery_signature_extracts_stable_token_and_patch_markers():
    service = RuntimeRecoveryService(session=None)  # type: ignore[arg-type]
    token_violation = SimpleNamespace(
        type="CODE_FRONTEND",
        executor="codex",
        last_error="Design contract violation in index.html: ad-hoc hex color #ec4899 is not in token_registry.colors.",
        result={},
    )
    patch_size_violation = SimpleNamespace(
        type="CODE_BACKEND",
        executor="codex",
        last_error="Action error: Patch too large for app.py (>40% change)",
        result={},
    )
    token_sig = service.build_failure_signature(token_violation, "validation_drift")
    patch_sig = service.build_failure_signature(patch_size_violation, "scope_violation")
    assert token_sig == "validation_drift:design_token_missing:#ec4899"
    assert patch_sig == "scope_violation:patch_too_large:app.py"


def test_same_signature_repeat_counter():
    assert _next_same_signature_count(prior_signature="", current_signature="a", prior_count=0) == 0
    assert _next_same_signature_count(prior_signature="a", current_signature="b", prior_count=4) == 0
    assert _next_same_signature_count(prior_signature="a", current_signature="a", prior_count=0) == 1
    assert _next_same_signature_count(prior_signature="a", current_signature="a", prior_count=1) == 2
