import asyncio
from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from app.runtime.recovery_policy import (
    FrontendReadinessState,
    _fix_recovery_scope,
    _frontend_readiness_state_from_error_text,
    _layout_composition_recovery_scope,
    classify_failure,
    plan_recovery,
)
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


def test_recovery_classifies_stack_test_strategy_mismatch():
    mismatch = SimpleNamespace(
        type="RUN_TESTS",
        status="FAILED",
        executor="test",
        last_error="Tests failed",
        result={"stack_mismatch_detected": True, "stack_mismatch_reason": "python_test_for_vue"},
    )
    assert classify_failure(mismatch) == "stack_test_strategy_mismatch"


def test_run_tests_stack_mismatch_has_spawn_fix_node_rule():
    work_item = SimpleNamespace(type="RUN_TESTS", status="FAILED")
    rule = plan_recovery(work_item, "stack_test_strategy_mismatch")
    assert rule is not None
    assert rule.action == "spawn_fix_node"


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


def test_recovery_classifies_missing_landing_zone_markers_as_foundation_bootstrap_required():
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        status="FAILED",
        executor="codex",
        last_error="LandingPage missing required zone markers; run GENESIS_FOUNDATION repair before CODE_FRONTEND.",
        result={},
    )
    assert classify_failure(work_item) == "foundation_bootstrap_required"


def test_recovery_classifies_missing_landing_page_file_as_foundation_bootstrap_required():
    work_item = SimpleNamespace(
        type="FIX_LAYOUT_COMPOSITION",
        status="FAILED",
        executor="codex",
        last_error="Patch could not be applied because apps/web/src/pages/LandingPage.vue does not exist. No changes made.",
        result={},
    )
    assert classify_failure(work_item) == "foundation_bootstrap_required"


def test_frontend_readiness_state_orders_foundation_before_layout():
    state = _frontend_readiness_state_from_error_text(
        "Patch could not be applied because apps/web/src/pages/LandingPage.vue does not exist. "
        "Tailwind governance violation in HeroSection.vue: missing max-width/container utility."
    )
    assert state == FrontendReadinessState.FOUNDATION_BROKEN


def test_frontend_readiness_state_classifies_composition_and_layout():
    assert _frontend_readiness_state_from_error_text(
        "CODE_FRONTEND composition zone violation in apps/web/src/pages/LandingPage.vue: missing required zone markers."
    ) == FrontendReadinessState.COMPOSITION_BROKEN
    assert _frontend_readiness_state_from_error_text(
        "Tailwind governance violation in apps/web/src/components/landing/HeroSection.vue: missing max-width/container utility."
    ) == FrontendReadinessState.LAYOUT_DEGRADED


def test_frontend_foundation_bootstrap_required_spawns_genesis_foundation():
    work_item = SimpleNamespace(type="CODE_FRONTEND", status="FAILED")
    rule = plan_recovery(work_item, "foundation_bootstrap_required")
    assert rule is not None
    assert rule.action == "spawn_fix_node"
    assert rule.spawn_type == "GENESIS_FOUNDATION"


def test_fix_layout_foundation_bootstrap_required_spawns_genesis_foundation():
    work_item = SimpleNamespace(type="FIX_LAYOUT_COMPOSITION", status="FAILED")
    rule = plan_recovery(work_item, "foundation_bootstrap_required")
    assert rule is not None
    assert rule.action == "spawn_fix_node"
    assert rule.spawn_type == "GENESIS_FOUNDATION"


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


def test_fix_recovery_scope_preserves_frontend_topology_when_feature_component_exists():
    implementation_files, _ = _fix_recovery_scope(
        {
            "related_files": [
                "apps/web/src/components/landing/TestimonialsSection.vue",
                "apps/web/src/pages/LandingPage.vue",
                "apps/web/src/App.vue",
            ],
            "target_files": ["apps/web/src/components/landing/tests/TestimonialsSection.spec.ts"],
        }
    )
    assert "apps/web/src/pages/LandingPage.vue" not in implementation_files
    assert "apps/web/src/components/landing/TestimonialsSection.vue" in implementation_files


def test_fix_recovery_scope_infers_frontend_file_from_framework_stderr_path():
    implementation_files, _ = _fix_recovery_scope(
        {
            "stderr": (
                "file: /private/tmp/ws/repo/apps/web/src/components/landing/TestimonialsSection.vue:12:199\n"
                "SyntaxError: [plugin vite:vue] ..."
            )
        }
    )
    assert "apps/web/src/components/landing/TestimonialsSection.vue" in implementation_files


def test_layout_composition_recovery_scope_uses_shell_files_and_excludes_section_components():
    scoped = _layout_composition_recovery_scope(
        {
            "target_files": ["apps/web/src/components/landing/CTASection.vue"],
            "related_files": ["apps/web/src/components/landing/TestimonialsSection.vue"],
            "expected_files": ["apps/web/src/pages/LandingPage.vue", "apps/web/src/layouts/PageShell.vue"],
        }
    )
    assert "apps/web/src/components/landing/CTASection.vue" not in scoped
    assert "apps/web/src/components/landing/TestimonialsSection.vue" not in scoped
    assert scoped == ["apps/web/src/pages/LandingPage.vue"]


def test_layout_composition_recovery_scope_falls_back_to_landing_page():
    scoped = _layout_composition_recovery_scope(
        {
            "target_files": ["apps/web/src/components/landing/CTASection.vue"],
            "related_files": ["apps/web/src/components/landing/TestimonialsSection.vue"],
            "expected_files": ["apps/web/src/components/landing/HeroSection.vue"],
        }
    )
    assert scoped == ["apps/web/src/LandingPage.vue"]


def test_layout_composition_recovery_scope_prefers_existing_path_from_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "apps/web/src").mkdir(parents=True, exist_ok=True)
    (repo / "apps/web/src/App.vue").write_text("<template><main /></template>\n", encoding="utf-8")
    scoped = _layout_composition_recovery_scope(
        {
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
            "related_files": ["apps/web/src/components/landing/CTASection.vue"],
            "expected_files": ["apps/web/src/LandingPage.vue"],
        },
        repo_path=str(repo),
    )
    assert scoped == ["apps/web/src/pages/LandingPage.vue"]
