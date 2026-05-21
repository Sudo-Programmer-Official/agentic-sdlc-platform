import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AIJobRun
from app.db.models import Project, Run, WorkItem
from app.runtime.context import RunContext
from app.runtime.codex_executor import (
    _added_patch_payload,
    _allow_adjacent_scope_expansion,
    _contains_probable_secret_leak,
    _derive_backend_topology_plan,
    _build_design_token_rewrite_map,
    _derive_frontend_topology_plan,
    _edit_budget_from_payload,
    _extract_structured_json_candidate,
    _fix_test_failure_writable_scope,
    _is_bootstrap_or_genesis_scope,
    _normalize_frontend_design_tokens,
    _operator_confirmation_next_action,
    replace_zone,
    _sanitize_frontend_scope_paths,
    _runtime_governance_mode,
    _emergency_warning_violation,
    _stability_warning_violation,
    _should_block_on_human_review_for_work_item,
    _should_block_for_operator_confirmation,
    _is_static_frontend_scope,
    _stage_scope_violations,
    _target_files_from_payload,
    _write_tests_writable_scope,
    _verification_from_action_scope,
    execute as module_execute,
    CodexExecutor,
)
from app.runtime.execution_contract import build_execution_contract
from app.runtime.mutation_governance import MutationGovernanceDecision
from app.runtime.patch_guard import evaluate_patch_guard
from app.runtime.frontend_topology import validate_frontend_topology
from app.runtime.component_capability_protocol import resolve_component_capability
from app.runtime.content_binding import build_binding_registry, extract_literals, rewrite_with_content_slots
from app.runtime.schemas.executor_io import Action
from app.schemas.run_narrative import RunPatchVerificationFinding, RunPatchVerificationSummary
from app.services.ai_policy import AIJobManager
from app.core.config import get_settings


class SequencePlanClient:
    def __init__(self, plans: list[dict]):
        self._plans = list(plans)
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []
        self.max_tokens: list[int | None] = []
        self.models: list[str | None] = []

    def method_name(self) -> str:
        return "sequence-plan-client"

    def sdk_version(self) -> str:
        return "test"

    async def generate(self, system_prompt, user_prompt, **kwargs):
        self.system_prompts.append(system_prompt)
        self.prompts.append(user_prompt)
        self.max_tokens.append(kwargs.get("max_tokens"))
        self.models.append(kwargs.get("model"))
        if not self._plans:
            raise AssertionError("No plan responses remaining")
        return json.dumps(self._plans.pop(0)), {"input_tokens": 1, "output_tokens": 1}


class SequenceRawClient:
    def __init__(self, responses: list[str | dict]):
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []
        self.max_tokens: list[int | None] = []
        self.models: list[str | None] = []

    def method_name(self) -> str:
        return "sequence-raw-client"

    def sdk_version(self) -> str:
        return "test"

    async def generate(self, system_prompt, user_prompt, **kwargs):
        self.system_prompts.append(system_prompt)
        self.prompts.append(user_prompt)
        self.max_tokens.append(kwargs.get("max_tokens"))
        self.models.append(kwargs.get("model"))
        if not self._responses:
            raise AssertionError("No raw responses remaining")
        response = self._responses.pop(0)
        raw = json.dumps(response) if isinstance(response, dict) else response
        return raw, {"input_tokens": 1, "output_tokens": 1}


@pytest.mark.anyio
async def test_codex_executor_module_execute_entrypoint_delegates(monkeypatch):
    class _StubExecutor:
        async def execute(self, work_item, context):
            return {
                "status": "DONE",
                "outputs": {"work_item_id": str(work_item.id)},
                "summary": "ok",
                "artifacts": [],
                "telemetry": {},
            }

    work_item = SimpleNamespace(id=uuid.uuid4())
    context = SimpleNamespace()
    monkeypatch.setattr("app.runtime.codex_executor._DEFAULT_EXECUTOR", _StubExecutor())
    result = await module_execute(work_item, context)
    assert result["status"] == "DONE"


@pytest.fixture
async def db_session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'codex-executor.db'}", future=True)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        await engine.dispose()


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


def test_operator_confirmation_gate_does_not_block_medium_risk_mutation():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="MEDIUM",
        findings=[
            RunPatchVerificationFinding(
                code="missing_tests",
                severity="warning",
                title="No nearby tests detected",
                detail="No nearby tests detected.",
                files=[],
            )
        ],
    )
    actions = [Action(type="write_file", path="index.html", content="<html></html>")]
    assert _should_block_for_operator_confirmation(verification, actions) is False


def test_operator_confirmation_gate_blocks_high_risk_mutation():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="HIGH",
        findings=[],
    )
    actions = [Action(type="apply_patch", path="app.py", patch="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n")]
    assert _should_block_for_operator_confirmation(verification, actions) is True


def test_operator_confirmation_gate_blocks_high_severity_finding():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="MEDIUM",
        findings=[
            RunPatchVerificationFinding(
                code="sensitive_scope",
                severity="high",
                title="Sensitive subsystem detected",
                detail="Sensitive subsystem.",
                files=["app/auth.py"],
            )
        ],
    )
    actions = [Action(type="write_file", path="app/auth.py", content="x")]
    assert _should_block_for_operator_confirmation(verification, actions) is True


def test_operator_confirmation_gate_blocks_broad_20_file_mutation():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="MEDIUM",
        file_count=20,
        findings=[],
    )
    actions = [Action(type="apply_patch", path="app.py", patch="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n")]
    assert _should_block_for_operator_confirmation(verification, actions) is True
    assert "decomposition plan" in _operator_confirmation_next_action(verification).lower()


def test_operator_confirmation_gate_4_file_missing_tests_does_not_block():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="MEDIUM",
        file_count=4,
        findings=[
            RunPatchVerificationFinding(
                code="missing_tests",
                severity="warning",
                title="No nearby tests detected",
                detail="No nearby tests detected.",
                files=[],
            )
        ],
    )
    actions = [Action(type="write_file", path="index.html", content="<html></html>")]
    assert _should_block_for_operator_confirmation(verification, actions) is False


def test_operator_confirmation_gate_genesis_bounded_missing_tests_does_not_block():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="MEDIUM",
        file_count=4,
        findings=[
            RunPatchVerificationFinding(
                code="missing_tests",
                severity="warning",
                title="No nearby tests detected",
                detail="No nearby tests detected.",
                files=[],
            )
        ],
    )
    actions = [Action(type="apply_patch", path="app.py", patch="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n")]
    assert _should_block_for_operator_confirmation(
        verification,
        actions,
        repository_state="GENESIS",
    ) is False


def test_operator_confirmation_gate_genesis_still_blocks_high_severity():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="MEDIUM",
        file_count=4,
        findings=[
            RunPatchVerificationFinding(
                code="protected_zone",
                severity="high",
                title="Protected zone touched",
                detail="Sensitive subsystem mutation.",
                files=["apps/api/app/runtime/codex_executor.py"],
            )
        ],
    )
    actions = [Action(type="write_file", path="apps/api/app/runtime/codex_executor.py", content="x")]
    assert _should_block_for_operator_confirmation(
        verification,
        actions,
        repository_state="GENESIS",
    ) is True


def test_operator_confirmation_gate_genesis_allows_bounded_actions_when_only_file_cap_exceeded():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="HIGH",
        file_count=9,
        findings=[
            RunPatchVerificationFinding(
                code="missing_tests",
                severity="warning",
                title="No nearby tests detected",
                detail="No nearby tests detected.",
                files=[],
            ),
            RunPatchVerificationFinding(
                code="file_cap_exceeded",
                severity="high",
                title="Patch exceeds normal file budget",
                detail="Planned scope exceeds normal autonomous cap.",
                files=["app.py"],
            ),
        ],
    )
    actions = [Action(type="apply_patch", path="app.py", patch="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n")]
    assert _should_block_for_operator_confirmation(
        verification,
        actions,
        repository_state="GENESIS",
    ) is False


def test_operator_confirmation_gate_genesis_still_blocks_wide_actions_when_file_cap_exceeded():
    verification = RunPatchVerificationSummary(
        status="REQUIRES_CONFIRMATION",
        requires_confirmation=True,
        risk_level="HIGH",
        file_count=9,
        findings=[
            RunPatchVerificationFinding(
                code="file_cap_exceeded",
                severity="high",
                title="Patch exceeds normal file budget",
                detail="Planned scope exceeds normal autonomous cap.",
                files=["app.py"],
            ),
        ],
    )
    actions = [
        Action(type="apply_patch", path="a.py", patch="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"),
        Action(type="apply_patch", path="b.py", patch="--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-a\n+b\n"),
        Action(type="apply_patch", path="c.py", patch="--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-a\n+b\n"),
    ]
    assert _should_block_for_operator_confirmation(
        verification,
        actions,
        repository_state="GENESIS",
    ) is True


def test_design_token_rewrite_map_uses_aliases_from_design_contract():
    project_contract = {
        "design_contract": {
            "token_registry": {
                "colors": {
                    "primary_500": "#2563eb",
                }
            },
            "rewrite_aliases": {
                "#ec4899": "primary_500",
            },
        }
    }
    rewrite_map = _build_design_token_rewrite_map(
        project_contract=project_contract,
        allowed_hex={"#2563eb"},
    )
    assert rewrite_map == {"#ec4899": "#2563eb"}


def test_normalize_frontend_design_tokens_rewrites_hex_deterministically():
    content = ".btn{background:#ec4899;color:#0f172a}"
    normalized, replacements = _normalize_frontend_design_tokens(
        content=content,
        allowed_hex={"#0f172a", "#2563eb"},
        rewrite_map={"#ec4899": "#2563eb"},
    )
    assert normalized == ".btn{background:#2563eb;color:#0f172a}"
    assert replacements == [("#ec4899", "#2563eb")]


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


def test_target_files_from_payload_includes_singular_scope_hints():
    target_files = _target_files_from_payload(
        {
            "target_file": "index.html",
            "path": "ignored.html",
        }
    )

    assert target_files == ["index.html", "ignored.html"]


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


def test_extract_structured_json_candidate_from_fenced_output():
    raw = (
        "Here is the patch plan.\n"
        "```json\n"
        "{\n"
        "  \"status\": \"DONE\",\n"
        "  \"message\": \"wrapped\",\n"
        "  \"warnings\": [],\n"
        "  \"actions\": [],\n"
        "  \"artifacts\": []\n"
        "}\n"
        "```\n"
    )
    candidate = _extract_structured_json_candidate(raw)
    assert candidate is not None
    payload = json.loads(candidate)
    assert payload["status"] == "DONE"
    assert payload["message"] == "wrapped"


def test_codex_executor_parse_codex_plan_accepts_wrapped_json_object():
    executor = CodexExecutor()
    raw = (
        "Plan follows:\n"
        "{"
        "\"status\":\"DONE\","
        "\"message\":\"ok\","
        "\"warnings\":[],"
        "\"actions\":[],"
        "\"artifacts\":[]"
        "}\nThanks."
    )
    plan = executor._parse_codex_plan(raw)
    assert plan.status == "DONE"
    assert plan.message == "ok"


def test_stage_scope_repair_candidate_allows_frontend_oversized_writefile_violation():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    allowed = executor._is_stage_scope_repair_candidate(
        work_item=work_item,
        violations=["CODE_FRONTEND write_file payload too large for index.html (25000 bytes > 24000)."],
    )

    assert allowed is True


def test_frontend_writefile_violations_flags_oversized_rewrite():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"]},
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="index.html",
            content=("a" * 30000),
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)

    assert len(violations) == 1
    assert "CODE_FRONTEND write_file payload too large" in violations[0]


def test_mutation_strategy_violations_allows_single_coherent_fallback_strategy():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")
    actions = [SimpleNamespace(type="apply_patch"), SimpleNamespace(type="note")]

    violations = executor._mutation_strategy_violations(
        work_item=work_item,
        selected_strategy="write_file",
        actions=actions,
    )

    assert violations == []


def test_mutation_strategy_violations_flags_mixed_mutating_action_types():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")
    actions = [SimpleNamespace(type="apply_patch"), SimpleNamespace(type="write_file")]

    violations = executor._mutation_strategy_violations(
        work_item=work_item,
        selected_strategy="write_file",
        actions=actions,
    )

    assert len(violations) == 1
    assert "mixed mutating action types" in violations[0]


def test_apply_patch_by_hunk_replacement_updates_file_when_context_matches(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    index_path = repo_root / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")
    executor = CodexExecutor(repo_root=repo_root)

    from app.runtime.tools.repo_tools import RepoTools

    repo = RepoTools(repo_root)
    patch = (
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<main>Portfolio</main>\n"
        "+<main>Rethemed portfolio</main>\n"
    )
    applied = executor._apply_patch_by_hunk_replacement(
        repo=repo,
        rel_path="index.html",
        patch_text=patch,
    )

    assert applied is True
    assert "Rethemed portfolio" in index_path.read_text(encoding="utf-8")


def test_apply_patch_by_hunk_replacement_returns_false_when_old_block_missing(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    index_path = repo_root / "index.html"
    index_path.write_text("<main>Different</main>\n", encoding="utf-8")
    executor = CodexExecutor(repo_root=repo_root)

    from app.runtime.tools.repo_tools import RepoTools

    repo = RepoTools(repo_root)
    patch = (
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<main>Portfolio</main>\n"
        "+<main>Rethemed portfolio</main>\n"
    )
    applied = executor._apply_patch_by_hunk_replacement(
        repo=repo,
        rel_path="index.html",
        patch_text=patch,
    )

    assert applied is False
    assert "Different" in index_path.read_text(encoding="utf-8")


def test_frontend_retry_cap_bump_active_for_static_scope_retry_payload():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"target_files": ["index.html"], "prior_patch_failures": 1},
    )

    assert executor._frontend_retry_cap_bump_active(work_item) is True
    assert executor._max_patch_lines_for(work_item) >= executor.max_patch_lines


def test_frontend_retry_cap_bump_inactive_without_retry_signal():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"target_files": ["index.html"]},
    )

    assert executor._frontend_retry_cap_bump_active(work_item) is False
    assert executor._max_patch_lines_for(work_item) == executor.max_patch_lines


def test_stage_scope_repair_candidate_allows_mutation_strategy_violation_for_frontend():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    allowed = executor._is_stage_scope_repair_candidate(
        work_item=work_item,
        violations=[
            "CODE_FRONTEND mutation_strategy violation: plan emitted mixed mutating action types (write_file and apply_patch)."
        ],
    )

    assert allowed is True


def test_static_frontend_scope_detects_html_css_only_targets():
    assert _is_static_frontend_scope({"expected_files": ["index.html", "styles.css"]}) is True
    assert _is_static_frontend_scope({"expected_files": ["index.html", "hero.py"]}) is False


def test_fix_test_failure_writable_scope_prefers_non_test_files():
    writable_scope = _fix_test_failure_writable_scope(
        {"target_files": ["test_index_html.py"]},
        None,
        ["test_index_html.py"],
        ["index.html", "test_index_html.py"],
    )

    assert writable_scope == ["index.html"]


def test_fix_test_failure_writable_scope_keeps_failing_tests_in_scope():
    writable_scope = _fix_test_failure_writable_scope(
        {
            "target_files": ["index.html"],
            "related_files": ["test_index_html.py"],
            "failing_test_files": ["test_index_html.py"],
        },
        None,
        ["index.html"],
        ["index.html", "test_index_html.py"],
    )

    assert writable_scope == ["index.html", "test_index_html.py"]


def test_write_tests_writable_scope_prefers_only_test_targets():
    writable_scope = _write_tests_writable_scope(
        target_files=["test_index_html.py"],
        allowed_files=["index.html", "test_index_html.py"],
    )

    assert writable_scope == ["test_index_html.py"]


def test_write_tests_writable_scope_falls_back_to_scoped_tests_when_targets_are_missing():
    writable_scope = _write_tests_writable_scope(
        target_files=[],
        allowed_files=["index.html", "tests/test_nav.py"],
    )

    assert writable_scope == ["tests/test_nav.py"]


def test_replace_zone_preserves_markers_and_replaces_body():
    original = (
        "<template>\n"
        "<!-- zone:hero:start -->\n"
        "<HeroPlaceholder />\n"
        "<!-- zone:hero:end -->\n"
        "</template>\n"
    )
    updated = replace_zone(original, "hero", "<HeroSection />")
    assert "<!-- zone:hero:start -->" in updated
    assert "<!-- zone:hero:end -->" in updated
    assert "<HeroSection />" in updated
    assert "<HeroPlaceholder />" not in updated


def test_runtime_governance_mode_defaults_to_stability_for_early_repository_state():
    assert _runtime_governance_mode({"repository_state": "GENESIS"}) == "stability"
    assert _runtime_governance_mode({"repository_state": "EARLY_BUILD"}) == "stability"
    assert _runtime_governance_mode({"repository_state": "ACTIVE_PRODUCT"}) == "stability"
    assert _runtime_governance_mode({"runtime_governance_mode": "governed", "repository_state": "GENESIS"}) == "governed"


def test_runtime_governance_mode_defaults_to_stability_when_unspecified():
    assert _runtime_governance_mode({}) == "stability"
    assert _runtime_governance_mode({"runtime_governance_mode": "", "repository_state": ""}) == "stability"
    assert _runtime_governance_mode({"runtime_governance_mode": "emergency"}) == "emergency"


def test_stability_warning_violation_matches_topology_and_primitive_failures():
    assert _stability_warning_violation("CODE_FRONTEND foundation topology violation in apps/web/src/pages/LandingPage.vue")
    assert _stability_warning_violation("CODE_FRONTEND primitive composition violation in component")
    assert _stability_warning_violation("Tailwind governance violation in apps/web/src/components/landing/HeroSection.vue: missing max-width/container utility.")
    assert _stability_warning_violation("visual quality gate: typography_hierarchy")
    assert _stability_warning_violation("Mutation authority violation: operation 'write_file' is not allowed for class POLISH.")
    assert _stability_warning_violation("SyntaxError in app.py") is False


def test_emergency_warning_violation_keeps_only_cosmetic_frontend_issues_non_blocking():
    assert _emergency_warning_violation("CODE_FRONTEND foundation topology violation in apps/web/src/pages/LandingPage.vue")
    assert _emergency_warning_violation("CODE_FRONTEND primitive composition violation in component")
    assert _emergency_warning_violation("visual quality gate: typography_hierarchy")
    assert _emergency_warning_violation("Project contract violation: missing max-width/container wrapper")
    assert _emergency_warning_violation("CODE_FRONTEND import normalization violation: patch touches files outside the planned scope")
    assert _emergency_warning_violation("Frontend import normalization could not resolve components: PrimaryButton.") is False
    assert _emergency_warning_violation("Capability governance violation: raw webhook URL detected") is False


def test_fix_recovery_normalizes_frontend_imports_deterministically(tmp_path: Path):
    repo_root = tmp_path
    (repo_root / "apps/web/src/components/ui").mkdir(parents=True, exist_ok=True)
    (repo_root / "apps/web/src/components/ui/Button.vue").write_text("<template><button /></template>\n", encoding="utf-8")
    content = (
        "<template>\n"
        "  <main><PrimaryButton /></main>\n"
        "</template>\n"
        "<script setup>\n"
        "import PrimaryButton from \"../../components/PrimaryButton.vue\";\n"
        "</script>\n"
    )
    action = Action(type="write_file", path="apps/web/src/pages/LandingPage.vue", content=content)
    work_item = SimpleNamespace(type="FIX_TEST_FAILURE")
    executor = CodexExecutor()

    normalized_actions, telemetry, violations = executor._normalize_frontend_import_actions(
        work_item=work_item,
        repo_root=repo_root,
        actions=[action],
    )
    assert violations == []
    assert telemetry["import_normalization_repairs"] >= 1
    assert telemetry["resolved_component_imports"]
    assert "../components/ui/Button.vue" in normalized_actions[0].content

    normalized_actions_2, telemetry_2, violations_2 = executor._normalize_frontend_import_actions(
        work_item=work_item,
        repo_root=repo_root,
        actions=normalized_actions,
    )
    assert violations_2 == []
    assert telemetry_2["import_normalization_repairs"] == 0


def test_select_mutation_strategy_prefers_write_file_for_single_file_static_frontend():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={"target_files": ["index.html"]},
        allowed_files=["index.html"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert "static_frontend_scope" in reasons
    assert drift_risk >= 0.5
    assert confidence >= 0.8
    assert zone == "layout_zone"


def test_select_mutation_strategy_honors_payload_override():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={"target_files": ["index.html"], "mutation_strategy": "apply_patch"},
        allowed_files=["index.html"],
    )

    assert selected == "apply_patch"
    assert fallback == ["write_file"]
    assert reasons == ["configured_in_payload"]
    assert drift_risk == 0.1
    assert confidence == 0.95
    assert zone == "layout_zone"


def test_select_mutation_strategy_prefers_write_file_for_bounded_html_scope_with_mixed_files():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    selected, fallback, reasons, _, _, _ = executor._select_mutation_strategy(
        work_item=work_item,
        payload={"target_files": ["index.html", "test_index_html.py"]},
        allowed_files=["index.html", "styles.css", "test_index_html.py"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert "bounded_frontend_candidate_scope" in reasons


def test_select_mutation_strategy_honors_recovery_write_file_preferred():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={"target_files": ["index.html"], "recovery_strategy": "write_file_preferred"},
        allowed_files=["index.html"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert reasons == ["recovery_strategy_write_file_preferred"]
    assert drift_risk >= 0.85
    assert confidence >= 0.85
    assert zone == "layout_zone"


def test_select_mutation_strategy_honors_recovery_write_file_preferred_for_backend():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_BACKEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={"target_files": ["app.py"], "recovery_strategy": "write_file_preferred"},
        allowed_files=["app.py"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert reasons == ["recovery_strategy_write_file_preferred"]
    assert drift_risk >= 0.8
    assert confidence >= 0.85
    assert zone == "logic_zone"


def test_select_mutation_strategy_prefers_write_file_for_backend_genesis_state():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_BACKEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={"target_files": ["app.py"], "repository_state": "GENESIS"},
        allowed_files=["app.py"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert reasons == ["repository_state_write_file_preferred"]
    assert drift_risk >= 0.65
    assert confidence >= 0.85
    assert zone == "logic_zone"


def test_backend_recovery_write_file_preference_does_not_hard_fail_on_apply_patch():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_BACKEND", payload={"recovery_strategy": "write_file_preferred"})
    actions = [SimpleNamespace(type="apply_patch", path="app.py", patch="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n")]

    violations = executor._mutation_strategy_violations(
        work_item=work_item,
        selected_strategy="write_file",
        actions=actions,
    )

    assert violations == []


def test_select_mutation_strategy_prefers_write_file_for_layout_sensitive_task_text():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={
            "target_files": ["src/components/NavBar.vue", "src/styles/main.css"],
            "task_title": "Implement responsive navigation with hamburger menu",
            "goal": "Refine homepage header layout behavior",
        },
        allowed_files=["src/components/NavBar.vue", "src/styles/main.css", "tests/test_nav.py"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert "layout_sensitive_task_text" in reasons
    assert drift_risk >= 0.5
    assert confidence >= 0.8
    assert zone == "layout_zone"


def test_select_mutation_strategy_escalates_to_write_file_after_prior_patch_failures():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")

    selected, fallback, reasons, drift_risk, confidence, zone = executor._select_mutation_strategy(
        work_item=work_item,
        payload={
            "target_files": ["index.html", "styles.css", "test_index_html.py", "README.md"],
            "task_title": "Navigation styling update",
            "prior_patch_failures": 2,
        },
        allowed_files=["index.html", "styles.css", "test_index_html.py", "README.md"],
    )

    assert selected == "write_file"
    assert fallback == ["apply_patch"]
    assert "prior_patch_failures" in reasons
    assert drift_risk >= 0.8
    assert confidence >= 0.9
    assert zone == "layout_zone"


def test_instructions_for_write_tests_discourage_new_third_party_dependencies():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "Restrict edits to these files unless validation proves a neighboring file is required: index.html." in instructions
    assert "prefer write_file with full file contents over fragile line-numbered patch hunks" in instructions
    assert "old and new expectations do not conflict" in instructions
    assert "Prefer behavior-oriented assertions over brittle implementation details" in instructions
    assert "allow equivalent outcomes aligned to the task intent" in instructions
    assert "This is a static frontend task." in instructions
    assert "Do not introduce new third-party imports such as BeautifulSoup or bs4" in instructions
    assert "html.parser" in instructions


def test_instructions_for_write_tests_frontend_uses_vitest_contract():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"expected_files": ["apps/web/src/components/landing/TestimonialsSection.vue"], "package_affinity": "apps/web"},
    )

    instructions = executor._instructions_for(work_item)

    assert "Framework-native test contract: this is a Vue/Vite frontend package." in instructions
    assert "Vitest + Vue Test Utils tests in TypeScript (*.spec.ts)" in instructions
    assert "Never generate Python test files for frontend Vue components." in instructions


def test_instructions_for_fix_test_failure_allow_scoped_test_refresh_for_stale_assertions():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="FIX_TEST_FAILURE",
        payload={"expected_files": ["index.html", "test_index_html.py"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "update the scoped tests to verify behavior instead of forcing obsolete markup" in instructions
    assert "Do not weaken or rewrite assertions just to make the suite pass." in instructions


def test_instructions_for_fix_test_failure_static_frontend_targets_index_first():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="FIX_TEST_FAILURE",
        payload={"expected_files": ["index.html", "test_index_html.py"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "target index.html first when it is in scope" in instructions
    assert "Edit a test file only when validation proves the assertion is stale or contradictory." in instructions


def test_instructions_for_static_frontend_prefer_minimal_apply_patch():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "prefer minimal apply_patch hunks" in instructions
    assert "never use placeholder headers such as @@ ... @@" in instructions


def test_instructions_for_static_frontend_recovery_write_file_override():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"], "recovery_strategy": "write_file_preferred"},
    )

    instructions = executor._instructions_for(work_item)

    assert "Recovery override: previous patch application drifted." in instructions
    assert "prefer write_file with full contents for the primary scoped file" in instructions


def test_instructions_include_frontend_mutation_contract_layer():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={"expected_files": ["apps/web/src/pages/LandingPage.vue"]})

    instructions = executor._instructions_for(work_item)

    assert "governed Vue 3 + Vite + Tailwind system" in instructions
    assert "Pages compose sections; sections compose governed components." in instructions
    assert "Forbidden patterns: style=, <style> blocks, raw hex colors, rgb(" in instructions


def test_instructions_include_component_topology_recovery_memory():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "expected_files": ["apps/web/src/components/landing/TestimonialsSection.vue"],
            "task_title": "Add Testimonials Section",
            "goal": "Add Testimonials section with reusable component",
            "recovery_reason": "design_token_violation",
        },
        last_error="inline style attributes are disallowed",
    )

    instructions = executor._instructions_for(work_item)

    assert "Topology-constrained component repair is active." in instructions
    assert "Never mutate index.html, App.vue, or unrelated components" in instructions
    assert "Previous attempt failed because:" in instructions
    assert "Specifically avoid: style=, <style>, #fff, #000, rgb(" in instructions


def test_instructions_enable_strict_output_contract_mode_when_recovery_flagged():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "expected_files": ["index.html"],
            "strict_output_contract_mode": True,
            "prior_output_contract_failures": 1,
        },
    )

    instructions = executor._instructions_for(work_item)

    assert "Strict recovery mode is active due to prior output-contract failures." in instructions
    assert "compact deterministic JSON only" in instructions


def test_instructions_include_selected_mutation_strategy():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"], "mutation_strategy": "write_file"},
    )

    instructions = executor._instructions_for(work_item)

    assert "Mutation strategy: write_file." in instructions
    assert "Prefer write_file for scoped deterministic updates" in instructions


def test_instructions_include_project_contract_brand_and_design_rules():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"]},
    )
    context = RunContext(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        project_contract={
            "summary": {
                "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
            },
            "brand_kit": {
                "tokens": {
                    "brand-primary": "#2563eb",
                    "brand-accent": "#ec4899",
                }
            },
            "design_system": {
                "components": ["HeroSection", "PrimaryButton"],
            },
            "enforcement": {
                "disallow_inline_styles": True,
                "enforce_color_tokens": True,
            },
        },
    )

    instructions = executor._instructions_for(work_item, context=context)

    assert "Project contract rules" in instructions
    assert "Use brand tokens when styling UI changes" in instructions
    assert "Prefer approved design-system components" in instructions
    assert "Avoid inline style attributes" in instructions
    assert "Avoid introducing ad-hoc hex colors" in instructions


def test_instructions_include_strict_project_contract_rejection_notice():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"]},
    )
    context = RunContext(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        project_contract={
            "summary": {
                "enforcement_enabled": True,
                "enforcement_mode": "strict",
                "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
            },
            "brand_kit": {
                "tokens": {
                    "brand-primary": "#2563eb",
                }
            },
            "design_system": {
                "components": ["HeroSection"],
            },
            "enforcement": {
                "enabled": True,
                "mode": "strict",
                "disallow_inline_styles": True,
                "enforce_color_tokens": True,
            },
        },
    )

    instructions = executor._instructions_for(work_item, context=context)

    assert "Project contract enforcement mode: STRICT." in instructions
    assert "You MUST follow project contract rules for this task." in instructions
    assert "Violation of these rules will cause rejection." in instructions


def test_instructions_include_design_context_packet():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"expected_files": ["index.html"]},
    )
    context = RunContext(
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        project_contract={
            "design_contract": {
                "experience_blueprint": "enterprise_operational",
                "identity": {"tone": "governed_structured_stable"},
                "typography": {"density": "compact"},
                "allowed_components": ["DashboardShell", "MetricCard"],
                "token_registry": {"colors": {"primary": "#1d4ed8"}},
            }
        },
    )

    instructions = executor._instructions_for(work_item, context=context)

    assert "DESIGN_CONTEXT_PACKET" in instructions
    assert "enterprise_operational" in instructions
    assert "DashboardShell" in instructions
    assert "compose from governed primitives only" in instructions


def test_ai_job_metadata_includes_design_context_packet_fields():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        key="CODE_FRONTEND",
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        id=uuid.uuid4(),
        payload={},
    )
    context_bundle = {
        "files": {"index.html": "<html></html>"},
        "meta": {
            "project_contract": {
                "design_contract": {
                    "experience_blueprint": "ai_native",
                    "identity": {"tone": "modern_dynamic_assistive"},
                    "typography": {"density": "comfortable"},
                    "allowed_components": ["PromptPanel", "AssistantThread"],
                    "token_registry": {"colors": {"primary": "#0f766e"}},
                }
            }
        },
    }
    request = executor._build_ai_job_request(work_item, context_bundle, allowed_files=["index.html"], execution_contract=None)

    assert request.metadata["design_experience_blueprint"] == "ai_native"
    assert request.metadata["design_visual_tone"] == "modern_dynamic_assistive"
    assert request.metadata["design_layout_density"] == "comfortable"
    assert request.metadata["design_allowed_components"] == ["PromptPanel", "AssistantThread"]


def test_design_validation_violations_detect_inline_style_and_adhoc_hex():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={})
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/page.tsx",
            content='<div style="color:#ff0000">Hello</div>',
        )
    ]
    project_contract = {
        "design_contract": {
            "token_registry": {"colors": {"primary": "#2563eb"}},
        },
        "enforcement": {
            "disallow_inline_styles": True,
            "enforce_color_tokens": True,
        },
    }

    violations = executor._design_validation_violations(
        work_item=work_item,
        actions=actions,
        project_contract=project_contract,
    )

    assert any("inline style attributes are disallowed" in item for item in violations)
    assert any("ad-hoc hex color" in item for item in violations)


def test_design_validation_violations_detect_unauthorized_components():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={})
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/page.tsx",
            content="<DashboardShell><RoguePanel /></DashboardShell>",
        )
    ]
    project_contract = {
        "design_contract": {
            "allowed_components": ["DashboardShell"],
        },
        "enforcement": {},
    }

    violations = executor._design_validation_violations(
        work_item=work_item,
        actions=actions,
        project_contract=project_contract,
    )

    assert any("unauthorized components" in item and "RoguePanel" in item for item in violations)


def test_design_validation_records_include_structured_fields():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={})
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/page.tsx",
            content='<div style="color:#ff0000"><RoguePanel /></div>',
        )
    ]
    project_contract = {
        "design_contract": {
            "allowed_components": ["DashboardShell"],
            "token_registry": {"colors": {"primary": "#2563eb"}},
        },
        "enforcement": {
            "disallow_inline_styles": True,
            "enforce_color_tokens": True,
        },
    }

    records = executor._design_validation_records(
        work_item=work_item,
        actions=actions,
        project_contract=project_contract,
    )

    assert any(record.get("type") == "design_contract_violation" for record in records)
    assert any(record.get("rule") == "disallow_inline_styles" for record in records)
    assert any(record.get("rule") == "enforce_color_tokens" and record.get("value") == "#ff0000" for record in records)
    assert any(record.get("rule") == "allowed_components" and "RoguePanel" in str(record.get("value")) for record in records)


def test_design_validation_recovery_auto_normalizes_inline_and_hex():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={"recovery_strategy": "design_token_auto_normalize"})
    action = SimpleNamespace(
        type="write_file",
        path="apps/web/src/components/landing/TestimonialsSection.vue",
        content='<section style="background:#fff;color:#ff0000">Hello</section>',
    )
    project_contract = {
        "design_contract": {
            "token_registry": {"colors": {"primary": "#2563eb"}},
        },
        "enforcement": {
            "disallow_inline_styles": True,
            "enforce_color_tokens": True,
        },
    }

    records = executor._design_validation_records(
        work_item=work_item,
        actions=[action],
        project_contract=project_contract,
    )

    assert records == []
    assert 'style="' not in action.content


def test_design_validation_strips_style_blocks_before_violation_escalation():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={})
    action = SimpleNamespace(
        type="write_file",
        path="apps/web/src/components/landing/TestimonialsSection.vue",
        content="<template><div>ok</div></template><style>.x{color:#fff}</style>",
    )
    project_contract = {
        "design_contract": {"token_registry": {"colors": {"primary": "#2563eb"}}},
        "enforcement": {"enforce_color_tokens": True},
    }

    records = executor._design_validation_records(
        work_item=work_item,
        actions=[action],
        project_contract=project_contract,
    )

    assert records == []
    assert "<style" not in action.content


def test_bootstrap_scope_detects_genesis_setup_and_early_build_state():
    assert _is_bootstrap_or_genesis_scope(SimpleNamespace(payload={"task_source": "genesis_setup"}))
    assert _is_bootstrap_or_genesis_scope(SimpleNamespace(payload={"task_source": "genesis.foundation"}))
    assert _is_bootstrap_or_genesis_scope(SimpleNamespace(payload={"repository_state": "EARLY_BUILD"}))


def test_human_review_blocking_skips_bootstrap_and_review_stages():
    assert _should_block_on_human_review_for_work_item(
        SimpleNamespace(type="GENERATE_ROUTE", payload={"task_source": "genesis"})
    ) is False
    assert _should_block_on_human_review_for_work_item(
        SimpleNamespace(type="REVIEW_DIFF", payload={})
    ) is False
    assert _should_block_on_human_review_for_work_item(
        SimpleNamespace(type="GENERATE_ROUTE", payload={"task_source": "feature"})
    ) is True


def test_secret_leak_detector_avoids_common_testing_terms_but_flags_real_secret_assignments():
    assert _contains_probable_secret_leak("def test_token_refresh_flow():\n    assert True\n") is False
    assert _contains_probable_secret_leak("OPENAI_API_KEY='sk-test-1234567890'") is True


def test_added_patch_payload_only_scans_added_lines():
    patch = (
        "diff --git a/test_app.py b/test_app.py\n"
        "--- a/test_app.py\n"
        "+++ b/test_app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-OPENAI_API_KEY='sk-old-secret'\n"
        "+assert token is not None\n"
    )
    payload = _added_patch_payload(patch)
    assert "OPENAI_API_KEY" not in payload
    assert "assert token is not None" in payload


def test_content_slot_rewriter_preserves_valid_closing_tag():
    content = "<title>B2B AI Sales Automation Landing Page</title>"
    literals = extract_literals(content)
    bindings = build_binding_registry(rel_path="index.vue", literals=literals)

    rewritten = rewrite_with_content_slots(content, bindings)

    assert "<//title>" not in rewritten.content
    assert "</title>" in rewritten.content
    assert "<ContentSlot" in rewritten.content


def test_content_binding_pass_skips_raw_html_entrypoints():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND")
    actions = [
        SimpleNamespace(
            type="write_file",
            path="index.html",
            content="<title>Landing</title><h1>Hero copy</h1>",
        )
    ]

    violations, records, telemetry = executor._content_binding_pass(work_item=work_item, actions=actions)

    assert violations == []
    assert records == []
    assert telemetry["content_binding_enabled"] is False
    assert "<ContentSlot" not in actions[0].content


def test_content_binding_disabled_does_not_introduce_contentslot():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={})
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/components/landing/TestimonialsSection.vue",
            content="<template><blockquote>{{ testimonial.quote }}</blockquote></template>",
        )
    ]

    violations, records, telemetry = executor._content_binding_pass(work_item=work_item, actions=actions)

    assert violations == []
    assert records == []
    assert telemetry["content_binding_enabled"] is False
    assert "ContentSlot" not in actions[0].content


def test_content_binding_disabled_falls_back_plain_text_when_contentslot_present():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={})
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/components/landing/TestimonialsSection.vue",
            content=(
                '<template><blockquote><ContentSlot content-key="quote" :fallback="testimonial.quote" />'
                "</blockquote></template>"
            ),
        )
    ]

    violations, records, telemetry = executor._content_binding_pass(work_item=work_item, actions=actions)

    assert violations == []
    assert records == []
    assert telemetry["content_binding_fallback_used"] is True
    assert "ContentSlot" not in actions[0].content
    assert "{{ testimonial.quote }}" in actions[0].content


def test_content_binding_enabled_allows_contentslot_in_design_contract(monkeypatch):
    monkeypatch.setenv("CONTENT_BINDING_ENABLED", "true")
    get_settings.cache_clear()
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="CODE_FRONTEND", payload={"content_binding_enabled": True})
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/components/landing/TestimonialsSection.vue",
            content='<template><ContentSlot content-key="quote" :fallback="testimonial.quote" /></template>',
        )
    ]
    project_contract = {
        "design_contract": {
            "enforcement": {"enabled": True},
            "allowed_components": ["HeroSection"],
            "components": {"registry": ["HeroSection"]},
        }
    }

    violations = executor._design_validation_records(
        work_item=work_item,
        actions=actions,
        project_contract=project_contract,
    )
    assert not violations


def test_feature_mode_blocks_full_shell_replacement_in_code_frontend():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><main>full rewrite</main></template>",
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("foundation topology violation" in item for item in violations)


def test_testimonials_task_requires_placeholder_replacement():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "task_title": "Add testimonials section",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><PageShell><TestimonialsPlaceholder /></PageShell></template>",
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("incomplete zone replacement" in item for item in violations)


def test_feature_task_cannot_create_isolated_pages():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "task_title": "Add testimonials section",
            "target_files": ["apps/web/src/pages/DashboardPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/DashboardPage.vue",
            content="<template><main>new page</main></template>",
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("composition zone violation" in item for item in violations)


def test_feature_task_must_preserve_landing_composition_zones():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "task_title": "Add testimonials section",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><PageShell><TestimonialsZone /></PageShell></template>",
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("composition zones must be preserved" in item for item in violations)


def test_feature_task_allows_landingpage_composition_mutation_when_topology_is_preserved():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "task_title": "Add hero section",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content=(
                "<template><PageShell>"
                "<HeroZone><HeroSection /></HeroZone>"
                "<FeatureZone />"
                "<TestimonialsZone />"
                "<CTAZone />"
                "</PageShell></template>"
            ),
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert not any("foundation topology violation" in item for item in violations)
    assert not any("composition zone violation" in item for item in violations)


def test_feature_can_replace_testimonials_placeholder_inside_testimonials_zone():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"mutation_class": "FEATURE", "repository_state": "ACTIVE_PRODUCT", "task_title": "Add testimonials section"},
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content=(
                "<template><PageShell>"
                "<HeroZone />"
                "<FeatureZone />"
                "<TestimonialsZone><TestimonialsSection /></TestimonialsZone>"
                "<CTAZone />"
                "</PageShell></template>"
            ),
        )
    ]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert not any("incomplete zone replacement" in item for item in violations)


def test_feature_can_insert_hero_section_inside_hero_zone():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "mutation_class": "FEATURE",
            "repository_state": "ACTIVE_PRODUCT",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content=(
                "<template><PageShell>"
                "<HeroZone><HeroSection /></HeroZone>"
                "<FeatureZone />"
                "<TestimonialsZone />"
                "<CTAZone />"
                "</PageShell></template>"
            ),
        )
    ]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert not any("foundation topology violation" in item for item in violations)
    assert not any("composition zone violation" in item for item in violations)


def test_landing_zone_auto_normalization_restores_missing_required_zones():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"mutation_class": "FEATURE", "runtime_governance_mode": "stability"},
    )
    actions = [
        Action(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><PageShell><section>Generated</section></PageShell></template>",
        )
    ]
    updated, warnings, violations = executor._auto_normalize_landing_zone_actions(work_item=work_item, actions=actions)
    assert not violations
    assert len(updated) == 1
    normalized = updated[0].content or ""
    assert "<HeroZone>" in normalized
    assert "<FeatureZone>" in normalized
    assert "<TestimonialsZone>" in normalized
    assert "<CTAZone>" in normalized
    assert warnings == []


def test_landing_zone_auto_normalization_places_hero_inside_hero_zone():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"mutation_class": "FEATURE", "runtime_governance_mode": "stability"},
    )
    actions = [
        Action(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><PageShell><HeroSection /></PageShell></template>",
        )
    ]
    updated, _, violations = executor._auto_normalize_landing_zone_actions(work_item=work_item, actions=actions)
    assert not violations
    normalized = updated[0].content or ""
    assert "<HeroZone>" in normalized
    assert "<HeroSection />" in normalized


def test_landing_zone_auto_normalization_inserts_placeholders_for_missing_zones():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"mutation_class": "POLISH", "runtime_governance_mode": "stability"},
    )
    actions = [
        Action(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><PageShell><HeroSection /></PageShell></template>",
        )
    ]
    updated, _, violations = executor._auto_normalize_landing_zone_actions(work_item=work_item, actions=actions)
    assert not violations
    normalized = updated[0].content or ""
    assert "<TestimonialsPlaceholder />" in normalized
    assert "<CTAPlaceholder />" in normalized


def test_normalized_landingpage_passes_patch_guard():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"mutation_class": "FEATURE", "runtime_governance_mode": "stability"},
    )
    actions = [
        Action(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><main>no zones</main></template>",
        )
    ]
    normalized_actions, _, violations = executor._auto_normalize_landing_zone_actions(work_item=work_item, actions=actions)
    assert not violations
    decision = evaluate_patch_guard(
        actions=normalized_actions,
        allowed_files=["apps/web/src/pages/LandingPage.vue"],
        file_budget=4,
        hard_file_budget=8,
        work_item_type="CODE_FRONTEND",
        work_item_payload={"mutation_class": "FEATURE", "zone_composer_required": True},
    )
    assert decision.ok


def test_stability_mode_does_not_fail_feature_landing_without_pageshell():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "mutation_class": "FEATURE",
            "runtime_governance_mode": "stability",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content=(
                "<template><main>"
                "<HeroZone><HeroSection /></HeroZone>"
                "<FeatureZone><FeaturePlaceholder /></FeatureZone>"
                "<TestimonialsZone><TestimonialsPlaceholder /></TestimonialsZone>"
                "<CTAZone><CTAPlaceholder /></CTAZone>"
                "</main></template>"
            ),
        )
    ]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert not any("LandingPage shell must preserve PageShell" in item for item in violations)


def test_feature_zone_composer_rewrites_landingpage_deterministically(tmp_path: Path):
    repo_root = tmp_path
    landing = repo_root / "apps/web/src/pages/LandingPage.vue"
    landing.parent.mkdir(parents=True, exist_ok=True)
    landing.write_text(
        "<template><PageShell>\n"
        "<!-- zone:hero:start -->\n<HeroPlaceholder />\n<!-- zone:hero:end -->\n"
        "<!-- zone:feature:start -->\n<FeatureZone />\n<!-- zone:feature:end -->\n"
        "<!-- zone:testimonials:start -->\n<TestimonialsPlaceholder />\n<!-- zone:testimonials:end -->\n"
        "<!-- zone:cta:start -->\n<CTAZone />\n<!-- zone:cta:end -->\n"
        "</PageShell></template>\n",
        encoding="utf-8",
    )
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={"mutation_class": "FEATURE", "task_title": "Add hero section", "repository_state": "ACTIVE_PRODUCT"},
    )
    actions = [
        Action(type="write_file", path="apps/web/src/components/landing/HeroSection.vue", content="<template><section>Hero</section></template>"),
        Action(type="write_file", path="apps/web/src/pages/LandingPage.vue", content="<template><main>bad rewrite</main></template>"),
    ]
    updated_actions, violations = executor._enforce_feature_zone_composer(
        work_item=work_item,
        repo_root=repo_root,
        actions=actions,
    )
    assert not violations
    landing_actions = [a for a in updated_actions if a.path == "apps/web/src/pages/LandingPage.vue"]
    assert len(landing_actions) == 1
    assert "<!-- zone:hero:start -->" in (landing_actions[0].content or "")
    assert "<HeroSection />" in (landing_actions[0].content or "")
    assert "<main>bad rewrite</main>" not in (landing_actions[0].content or "")


def test_feature_cannot_delete_cta_zone():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "mutation_class": "FEATURE",
            "repository_state": "ACTIVE_PRODUCT",
            "target_files": ["apps/web/src/pages/LandingPage.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/pages/LandingPage.vue",
            content="<template><PageShell><HeroZone /><FeatureZone /><TestimonialsZone /></PageShell></template>",
        )
    ]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("CTAZone" in item and "composition zones must be preserved" in item for item in violations)


def test_feature_cannot_replace_landingpage_with_bare_main():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "mutation_class": "FEATURE",
            "repository_state": "ACTIVE_PRODUCT",
            "target_files": ["apps/web/src/App.vue", "apps/web/src/layouts/PageShell.vue"],
        },
    )
    actions = [SimpleNamespace(type="write_file", path="apps/web/src/pages/LandingPage.vue", content="<template><main>minimal</main></template>")]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("LandingPage shell must preserve PageShell" in item for item in violations)


def test_feature_cannot_mutate_app_or_pageshell_files():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "mutation_class": "FEATURE",
            "repository_state": "ACTIVE_PRODUCT",
            "target_files": ["apps/web/src/App.vue", "apps/web/src/layouts/PageShell.vue"],
        },
    )
    actions = [
        SimpleNamespace(type="write_file", path="apps/web/src/App.vue", content="<template><PageShell /></template>"),
        SimpleNamespace(type="write_file", path="apps/web/src/layouts/PageShell.vue", content="<template><main/></template>"),
    ]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert sum("may not fully replace App.vue or PageShell.vue" in item for item in violations) == 2


def test_testimonials_component_must_compose_governed_primitives():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "runtime_governance_mode": "governed",
            "task_title": "Add testimonials section",
            "target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/components/landing/TestimonialsSection.vue",
            content="<template><section><h2>What Customers Say</h2><div>raw card</div></section></template>",
        )
    ]

    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("primitive composition violation" in item for item in violations)


def test_stability_mode_blocks_unverified_testimonial_primitives():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_FRONTEND",
        payload={
            "task_source": "feature",
            "repository_state": "ACTIVE_PRODUCT",
            "runtime_governance_mode": "stability",
            "task_title": "Add testimonials section",
            "primitive_registry": {
                "SectionContainer": {"status": "verified_visual"},
                "SectionHeading": {"status": "stable"},
                "ContentGrid": {"status": "experimental"},
                "TestimonialCard": {"status": "verified_visual"},
            },
            "target_files": ["apps/web/src/components/landing/TestimonialsSection.vue"],
        },
    )
    actions = [
        SimpleNamespace(
            type="write_file",
            path="apps/web/src/components/landing/TestimonialsSection.vue",
            content="<template><SectionContainer><SectionHeading/>"
            "<ContentGrid><TestimonialCard/></ContentGrid></SectionContainer></template>",
        )
    ]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("stability mode forbids unverified primitives" in item for item in violations)


def test_adjacent_scope_expansion_allows_dependency_file_in_genesis_repair():
    work_item = SimpleNamespace(type="FIX_TEST_FAILURE", payload={"repository_state": "GENESIS"})
    assert _allow_adjacent_scope_expansion(work_item=work_item, extra_files=["requirements.txt"])
    assert not _allow_adjacent_scope_expansion(work_item=work_item, extra_files=["apps/api/app/main.py"])


def test_adjacent_scope_expansion_allows_dependency_file_for_fix_test_failure_without_repository_state():
    work_item = SimpleNamespace(type="FIX_TEST_FAILURE", payload={})
    assert _allow_adjacent_scope_expansion(work_item=work_item, extra_files=["requirements.txt"])


def test_instructions_for_plan_stage_forbid_mutations():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="PLAN_DAG",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "Do not mutate repository files." in instructions
    assert "Return only note actions" in instructions


def test_instructions_for_review_stage_forbid_mutations():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="REVIEW_DIFF",
        payload={"expected_files": ["index.html"]},
    )

    instructions = executor._instructions_for(work_item)

    assert "This is a review task." in instructions
    assert "Return only note actions" in instructions
    assert "Do not mutate repository files." in instructions
    assert "Never emit apply_patch, write_file, or delete_file actions." in instructions
    assert "prefer write_file" not in instructions


def test_system_prompt_for_review_stage_forbids_mutations():
    executor = CodexExecutor()
    prompt = executor._system_prompt_for(SimpleNamespace(type="REVIEW_DIFF"))

    assert "automated code review worker" in prompt
    assert "Return only note actions" in prompt
    assert "Never emit apply_patch, write_file, or delete_file actions." in prompt


def test_system_prompt_for_plan_stage_forbids_mutations():
    executor = CodexExecutor()
    prompt = executor._system_prompt_for(SimpleNamespace(type="PLAN_DAG"))

    assert "automated code review worker" in prompt
    assert "Return only note actions" in prompt
    assert "Never emit apply_patch, write_file, or delete_file actions." in prompt


def test_write_tests_stage_rejects_non_test_file_mutations():
    work_item = SimpleNamespace(type="WRITE_TESTS")

    violations = _stage_scope_violations(
        work_item,
        [],
        ["index.html", "test_index_html.py"],
    )

    assert violations == [
        "WRITE_TESTS may only modify Python test files; received out-of-scope file index.html."
    ]


def test_write_tests_stage_frontend_rejects_python_test_mutations():
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"package_affinity": "apps/web", "architecture_profile": {"frontend_stack": "vue_vite"}},
    )

    violations = _stage_scope_violations(
        work_item,
        [],
        ["apps/web/src/components/landing/test_TestimonialsSection_vue.py"],
    )

    assert violations == [
        "WRITE_TESTS(frontend) may only modify JS/TS test files (*.spec.*|*.test.*) under frontend scope; received out-of-scope file apps/web/src/components/landing/test_TestimonialsSection_vue.py."
    ]


def test_plan_stage_rejects_mutating_actions():
    work_item = SimpleNamespace(type="PLAN_DAG")
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    violations = _stage_scope_violations(
        work_item,
        [Action(type="apply_patch", patch=patch)],
        ["index.html"],
    )

    assert violations == [
        "PLAN work items may only return note actions; mutating file operations are out of scope."
    ]


def test_review_stage_rejects_mutating_actions():
    work_item = SimpleNamespace(type="REVIEW_DIFF")
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    violations = _stage_scope_violations(
        work_item,
        [Action(type="apply_patch", patch=patch)],
        ["index.html"],
    )

    assert violations == [
        "REVIEW work items may only return note actions; mutating file operations are out of scope."
    ]


def test_patch_guard_accepts_index_html_apply_patch_scope():
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    decision = evaluate_patch_guard(
        actions=[Action(type="apply_patch", patch=patch)],
        allowed_files=["index.html"],
    )

    assert decision.touched_files == ["index.html"]
    assert decision.ok is True


def test_patch_guard_rejects_pycache_and_compiled_artifacts():
    patch = (
        "diff --git a/__pycache__/test_index_html.cpython-312.pyc b/__pycache__/test_index_html.cpython-312.pyc\n"
        "--- a/__pycache__/test_index_html.cpython-312.pyc\n"
        "+++ b/__pycache__/test_index_html.cpython-312.pyc\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    decision = evaluate_patch_guard(
        actions=[Action(type="apply_patch", patch=patch)],
        allowed_files=["__pycache__/test_index_html.cpython-312.pyc"],
    )

    assert decision.ok is False
    assert any("runtime cache artifacts" in msg for msg in decision.violations)


def test_patch_guard_rejects_db_logic_inside_route_layer():
    action = Action(
        type="write_file",
        path="apps/api/app/routes/leads.py",
        content=(
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.post('/leads')\n"
            "def create_lead(session):\n"
            "    session.execute('select 1')\n"
            "    return {'ok': True}\n"
        ),
    )
    decision = evaluate_patch_guard(
        actions=[action],
        allowed_files=["apps/api/app/routes/leads.py"],
        work_item_type="GENERATE_ROUTE",
        work_item_payload={
            "backend_topology_plan": {
                "planned_files": ["apps/api/app/routes/leads.py"],
                "routes": ["apps/api/app/routes/leads.py"],
                "services": ["apps/api/app/services/leads_service.py"],
                "repositories": ["apps/api/app/repositories/leads_repository.py"],
                "capability_modules": ["apps/api/app/capabilities/crm_sync_binding.py"],
                "allowed_capabilities": ["crm_sync"],
            }
        },
    )
    assert decision.ok is False
    assert any("Routes must not include DB logic" in message for message in decision.violations)


def test_patch_guard_rejects_oversized_backend_entrypoint_rewrite():
    dense_backend = "\n".join([f"def handler_{idx}(): return {idx}" for idx in range(220)]) + "\n"
    action = Action(type="write_file", path="apps/api/app/main.py", content=dense_backend)
    decision = evaluate_patch_guard(
        actions=[action],
        allowed_files=["apps/api/app/main.py"],
        work_item_type="CODE_BACKEND",
        work_item_payload={
            "backend_topology_plan": {
                "planned_files": ["apps/api/app/main.py"],
                "routes": [],
                "services": [],
                "repositories": [],
                "capability_modules": [],
                "allowed_capabilities": ["crm_sync"],
            }
        },
    )
    assert decision.ok is False
    assert any("oversized entrypoint mutation" in message for message in decision.violations)


def test_patch_guard_blocks_polish_rewrite_of_landing_page():
    action = Action(
        type="write_file",
        path="apps/web/src/pages/LandingPage.vue",
        content="<template><main>replaced</main></template>\n",
    )
    decision = evaluate_patch_guard(
        actions=[action],
        allowed_files=["apps/web/src/pages/LandingPage.vue"],
        work_item_type="CODE_FRONTEND",
        work_item_payload={
            "mutation_class": "POLISH",
            "allowed_operations": ["apply_patch"],
            "forbidden_operations": ["replace_landing_page"],
            "protected_files": ["apps/web/src/pages/LandingPage.vue"],
            "zone_composer_required": True,
        },
    )
    assert decision.ok is False
    assert any("Mutation authority violation" in message or "Shell protection violation" in message for message in decision.violations)


def test_patch_guard_allows_feature_zone_patch_without_explicit_zone_markers():
    action = Action(
        type="apply_patch",
        path="apps/web/src/pages/LandingPage.vue",
        patch=(
            "diff --git a/apps/web/src/pages/LandingPage.vue b/apps/web/src/pages/LandingPage.vue\n"
            "--- a/apps/web/src/pages/LandingPage.vue\n"
            "+++ b/apps/web/src/pages/LandingPage.vue\n"
            "@@ -1 +1 @@\n"
            "-<template><main /></template>\n"
            "+<template><main class='p-6' /></template>\n"
        ),
    )
    decision = evaluate_patch_guard(
        actions=[action],
        allowed_files=["apps/web/src/pages/LandingPage.vue"],
        work_item_type="CODE_FRONTEND",
        work_item_payload={
            "mutation_class": "FEATURE",
            "allowed_operations": ["apply_patch", "write_file"],
            "zone_composer_required": True,
        },
    )
    assert decision.ok is True
    assert not any("Zone composition violation" in message for message in decision.violations)


def test_codex_executor_patch_parsers_preserve_index_html_paths():
    executor = CodexExecutor()
    patch = (
        "diff --git a/index.html b/index.html\n"
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -1 +1 @@\n"
        "-<body>Old</body>\n"
        "+<body>New</body>\n"
    )

    assert executor._paths_from_diff(patch) == ["index.html"]
    assert executor._parse_patch_changes(patch) == {"index.html": 2}


def test_patch_structure_error_detects_hunk_without_file_headers():
    executor = CodexExecutor()
    patch = (
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    assert executor._patch_structure_error(patch) == "Patch is missing file headers (---/+++) before diff hunks."


def test_patch_ratio_for_single_file_static_frontend_scope_is_unbounded():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="PLAN_DAG",
        payload={"expected_files": ["index.html"]},
    )

    assert executor._patch_ratio_for(work_item) == float("inf")


def test_patch_ratio_for_write_tests_scope_is_unbounded():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="WRITE_TESTS",
        payload={"expected_files": ["test_index_html.py"]},
    )

    assert executor._patch_ratio_for(work_item) == float("inf")


def test_patch_ratio_for_non_frontend_plan_scope_preserves_default_plan_limit():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="PLAN_DAG",
        payload={"expected_files": ["app.py"]},
    )

    assert executor._patch_ratio_for(work_item) == 0.6


def test_patch_ratio_for_backend_genesis_scope_is_unbounded():
    executor = CodexExecutor()
    work_item = SimpleNamespace(
        type="CODE_BACKEND",
        payload={"target_files": ["app.py"], "repository_state": "GENESIS"},
    )

    assert executor._patch_ratio_for(work_item) == float("inf")


def test_patch_ratio_bypass_flag_applies_only_to_app_py():
    executor = CodexExecutor()
    executor.settings.codex_bypass_app_py_patch_ratio_limit = True
    assert executor._should_bypass_patch_ratio_limit("app.py") is True
    assert executor._should_bypass_patch_ratio_limit("apps/api/app/main.py") is False
    assert executor._should_bypass_patch_ratio_limit("index.html") is False


def test_operator_confirmation_bypass_flag_overrides_required_confirmation():
    executor = CodexExecutor()
    decision = MutationGovernanceDecision(
        requires_confirmation=True,
        mutation_class="STRUCTURAL_OR_BROAD_MUTATION",
        reason="operator_confirmation_required_by_verifier",
    )

    executor.settings.codex_bypass_operator_confirmation_required = False
    kept = executor._maybe_bypass_operator_confirmation(decision)
    assert kept.requires_confirmation is True

    executor.settings.codex_bypass_operator_confirmation_required = True
    bypassed = executor._maybe_bypass_operator_confirmation(decision)
    assert bypassed.requires_confirmation is False
    assert bypassed.reason == "operator_confirmation_bypassed_by_flag"


def test_human_review_gate_respects_operator_confirmation_bypass_flag():
    executor = CodexExecutor()
    work_item = SimpleNamespace(type="GENERATE_ROUTE", payload={"task_source": "feature"})

    executor.settings.codex_bypass_operator_confirmation_required = False
    assert executor._should_block_on_human_review_gate(work_item) is True

    executor.settings.codex_bypass_operator_confirmation_required = True
    assert executor._should_block_on_human_review_gate(work_item) is False


def test_patch_guard_uses_apply_patch_path_when_diff_headers_are_missing():
    decision = evaluate_patch_guard(
        actions=[
            Action(
                type="apply_patch",
                path="test_index_html.py",
                patch=(
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
            )
        ],
        allowed_files=["test_index_html.py"],
    )

    assert decision.touched_files == ["test_index_html.py"]
    assert decision.ok is True


@pytest.mark.anyio
async def test_codex_executor_repairs_plan_stage_mutation_by_regenerating_notes(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    original_html = "<nav><a href='#home'>Home</a></nav>\n"
    index_path.write_text(original_html, encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Plan stage scope repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="PLAN_DAG",
            key="PLAN_DAG",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "mutating plan",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "diff --git a/index.html b/index.html\n"
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -1 +1 @@\n"
                            "-<nav><a href='#home'>Home</a></nav>\n"
                            "+<nav style='background:pink'><a href='#home'>Home</a></nav>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "repaired plan",
                "warnings": [],
                "actions": [
                    {
                        "type": "note",
                        "text": "Update index.html navigation styles to a pink gradient with white text, then add targeted validation and review steps.",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Change navigation color to pink",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Plan navigation color update",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "PLAN_DAG",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert index_path.read_text(encoding="utf-8") == original_html
    assert len(client.prompts) == 2
    assert "The previous action plan violated the stage scope." in client.prompts[1]
    assert "This is a planning stage. Return only note actions" in client.prompts[1]
    assert result["payload"]["patch_guard"]["touched_files"] == []
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_codex_executor_retries_project_contract_violation_before_patch_guard(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main><h1>Portfolio</h1></main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Project contract retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "initial patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main style='color:#ff00aa'><h1>Portfolio</h1></main>\n",
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "contract-compliant patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='hero-shell'><h1>Portfolio</h1></main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Retheme the hero section",
                    "expected_files": ["index.html"],
                },
                project_contract={
                    "summary": {
                        "enforcement_enabled": True,
                        "enforcement_mode": "strict",
                        "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
                    },
                    "enforcement": {
                        "enabled": True,
                        "mode": "strict",
                        "disallow_inline_styles": True,
                        "enforce_color_tokens": True,
                        "allowed_hex_values": ["#2563eb"],
                        "active_rules": ["disallow_inline_styles", "enforce_color_tokens"],
                    },
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "style=" not in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "violated the project contract" in client.prompts[1]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"
    assert result["payload"]["patch_guard"]["project_enforcement_mode"] == "strict"


@pytest.mark.anyio
async def test_codex_executor_repairs_placeholder_patch_by_regenerating_plan(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main><section id='projects'><p>Projects section coming soon.</p></section></main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Frontend patch repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="SHOWCASE_PROJECTS",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "patch": (
                            "diff --git a/index.html b/index.html\n"
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ ... @@\n"
                            "-<p>Projects section coming soon.</p>\n"
                            "+<div class='projects-list'><article>Portfolio Website</article></div>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": (
                            "<main>\n"
                            "  <section id='projects'>\n"
                            "    <h2>Projects</h2>\n"
                            "    <div class='projects-list'>\n"
                            "      <article>Portfolio Website</article>\n"
                            "      <article>Task Tracker App</article>\n"
                            "      <article>Weather Dashboard</article>\n"
                            "    </div>\n"
                            "  </section>\n"
                            "</main>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError("Patch apply error: Patch check failed: error: patch with only garbage at line 5")

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add showcase projects section",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Implement showcase projects section",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "Task Tracker App" in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "Do not use placeholder hunk headers such as @@ ... @@." in client.prompts[1]


@pytest.mark.anyio
async def test_codex_executor_repairs_hunk_only_patch_by_regenerating_plan(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main><p>Portfolio</p></main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Write tests patch repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "test_index_html.py"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "test_index_html.py",
                        "patch": (
                            "@@ -1 +1,8 @@\n"
                            "+def test_index_html_contains_main():\n"
                            "+    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "+        assert '<main>' in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            "def test_index_html_contains_main():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert '<main>' in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add tests for contact section",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add tests for contact section",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_contains_main" in (tmp_path / "test_index_html.py").read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "Do not return hunk-only patch fragments that start with @@ before file headers." in client.prompts[1]


@pytest.mark.anyio
async def test_codex_executor_retries_truncated_json_with_higher_token_cap(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Frontend parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="THEME_PORTFOLIO",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            (
                "{"
                "\"status\":\"DONE\","
                "\"message\":\"patched\","
                "\"warnings\":[],"
                "\"actions\":[{"
                "\"type\":\"apply_patch\","
                "\"path\":\"index.html\","
                "\"patch\":\"diff --git a/index.html b/index.html\\n--- a/index.html\\n+++ b/index.html\\n@@ -1 +1 @@\\n-<main>Portfolio</main>\\n+<main>Rethemed"
            ),
            {
                "status": "DONE",
                "message": "patched after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='theme-shell'>Rethemed portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Retheme the single-file portfolio",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Implement themed portfolio shell",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "Rethemed portfolio" in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "truncated" in client.prompts[1]
    assert "Do not reconsider the broader feature plan" in client.prompts[1]
    assert "For single-file HTML/CSS/JS edits, prefer minimal apply_patch hunks" in client.prompts[1]
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert client.max_tokens[0] > 1200
    assert client.max_tokens[1] > client.max_tokens[0]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_codex_executor_retries_invalid_patch_repair_with_forced_writefile(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Patch repair fallback", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="PATCH_REPAIR_RECOVERY",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "initial invalid patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": "@@ ... @@\n-<main>Portfolio</main>\n+<main>Rethemed portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            }
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    call_count = {"value": 0}

    async def fake_repair_plan_after_patch_failure(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise ValueError("Patch repair output was invalid: Unterminated string starting at: line 9 column 18 (char 304)")
        repair_raw = json.dumps(
            {
                "status": "DONE",
                "message": "repaired with write_file",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='theme-shell'>Rethemed portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            }
        )
        return (
            executor._parse_codex_plan(repair_raw),
            repair_raw,
            {"input_tokens": 1, "output_tokens": 1},
            "tier_premium",
            "gpt-4.1",
        )

    monkeypatch.setattr(executor, "_repair_plan_after_patch_failure", fake_repair_plan_after_patch_failure)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Recover malformed patch-repair output with deterministic write mode",
                    "expected_files": ["index.html"],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    # Deterministic frontend fallback should avoid model-driven patch-repair calls.
    assert call_count["value"] == 0
    assert "Rethemed portfolio" in index_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_review_diff_parse_retry_returns_note_actions_and_escalates(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    (tmp_path / "index.html").write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Review diff parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="REVIEW_DIFF",
            key="REVIEW_DIFF",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            (
                "{"
                "\"status\":\"DONE\","
                "\"message\":\"reviewed\","
                "\"warnings\":[],"
                "\"actions\":[{"
                "\"type\":\"apply_patch\","
                "\"patch\":\"diff --git a/index.html b/index.html\\n--- a/index.html\\n+++ b/index.html\\n@@ -1 +1 @@\\n-<main>Portfolio</main>\\n+<main>Reviewed"
            ),
            {
                "status": "DONE",
                "message": "reviewed after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "note",
                        "text": "Review passed. Navigation premium badge is scoped to index.html and no blocking issues were found.",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Review the premium navigation change",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Review the bounded navigation update",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "REVIEW_DIFF",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert len(client.prompts) == 2
    assert all("automated code review worker" in prompt for prompt in client.system_prompts)
    assert "This is a review stage. Return only note actions" in client.prompts[1]
    assert "Never emit apply_patch, write_file, or delete_file actions" in client.prompts[1]
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_plan_dag_parse_retry_runs_once_even_when_policy_disables_general_retries(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    (tmp_path / "index.html").write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Planner parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="PLAN_DAG",
            key="PLAN_DAG",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            "{\"status\":\"DONE\",\"message\":\"plan",
            {
                "status": "DONE",
                "message": "planned after parse retry",
                "warnings": [],
                "actions": [{"type": "note", "text": "bounded plan confirmed"}],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Create a portfolio project",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Plan the bounded portfolio change",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "PLAN_DAG",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert len(client.prompts) == 2
    assert "structured output retry 1" in client.prompts[1].lower()
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert client.max_tokens[1] > client.max_tokens[0]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_write_tests_parse_retry_escalates_to_premium_model(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    (tmp_path / "index.html").write_text("<main>Portfolio</main>\n", encoding="utf-8")
    test_path = tmp_path / "test_index_html.py"
    test_path.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Write tests parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={"target_files": ["test_index_html.py"], "related_files": ["index.html"]},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            "{\"status\":\"DONE\",\"message\":\"tests",
            {
                "status": "DONE",
                "message": "tests after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            "def test_index_html_exists():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert '<main>' in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Write validation tests for the portfolio page",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add bounded HTML validation tests",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_exists" in test_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "structured output retry 1" in client.prompts[1].lower()
    assert client.max_tokens[0] >= 3200
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert client.max_tokens[1] > client.max_tokens[0]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_codex_executor_repairs_unapplyable_patch_by_regenerating_plan(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")
    test_path = tmp_path / "test_index_html.py"
    base_tests = (
        "def test_index_html_exists():\n"
        "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
        "        assert '<main>' in handle.read()\n"
        "\n"
        "def test_index_html_contact_links_exist():\n"
        "    has_github = True\n"
        "    has_linkedin = True\n"
        "    assert has_github or has_linkedin, 'Contact section should have a GitHub or LinkedIn link placeholder.'\n"
    )
    test_path.write_text(base_tests, encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Write tests unapplyable patch repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "test_index_html.py"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "test_index_html.py",
                        "patch": (
                            "--- a/test_index_html.py\n"
                            "+++ b/test_index_html.py\n"
                            "@@ -97,6 +97,18 @@\n"
                            "     assert has_github or has_linkedin, 'Contact section should have a GitHub or LinkedIn link placeholder.'\n"
                            " \n"
                            "+import re\n"
                            "+\n"
                            "+def test_index_html_has_theme_styles():\n"
                            "+    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "+        content = handle.read().lower()\n"
                            "+    assert '<style' in content or re.search(r'<link[^>]+rel=[\"\\']stylesheet[\"\\']', content)\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            base_tests
                            + "\n"
                            + "import re\n"
                            + "\n"
                            + "def test_index_html_has_theme_styles():\n"
                            + "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            + "        content = handle.read().lower()\n"
                            + "    assert '<style' in content or re.search(r'<link[^>]+rel=[\"\\']stylesheet[\"\\']', content)\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError(
            "Patch apply error: Patch check failed: error: patch failed: test_index_html.py:97\n"
            "error: test_index_html.py: patch does not apply"
        )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add tests for themed portfolio styles",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add tests for themed portfolio styles",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_has_theme_styles" in test_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 2
    assert "patch does not apply" in client.prompts[1]
    assert "after a patch-apply failure, do not emit apply_patch" in client.prompts[1]
    assert "Emit write_file actions with full updated contents for scoped Python test files." in client.prompts[1]


@pytest.mark.anyio
async def test_codex_executor_retries_truncated_patch_repair_output(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Fix failure repair parse retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["index.html"],
                "related_files": ["test_index_html.py"],
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "first fix patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -99,3 +99,5 @@\n"
                            "-<main>Portfolio</main>\n"
                            "+<section class=\"hero\"><main>Portfolio</main></section>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            "{\"status\":\"DONE\",\"message\":\"repair",
            {
                "status": "DONE",
                "message": "repair after parse retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<section class=\"hero\"><main>Portfolio</main></section>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError(
            "Patch apply error: Patch check failed: error: patch failed: index.html:99\n"
            "error: index.html: patch does not apply"
        )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Fix the hero markup after validation failed",
                    "expected_files": ["index.html", "test_index_html.py"],
                    "steps": [
                        {
                            "title": "Fix failing hero validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "FIX_TEST_FAILURE",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "class=\"hero\"" in index_path.read_text(encoding="utf-8")
    assert len(client.prompts) == 3
    assert "patch does not apply" in client.prompts[1]
    assert "structured output retry 1" in client.prompts[2].lower()
    assert client.max_tokens[2] > client.max_tokens[1]


@pytest.mark.anyio
async def test_code_frontend_patch_repair_prefers_write_file_for_static_scope(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Frontend patch drift repair", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="QUEUED",
            executor="codex",
            payload={"target_files": ["index.html"]},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -90,4 +90,4 @@\n"
                            "-<main>Portfolio</main>\n"
                            "+<main>Updated Portfolio</main>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            {
                "status": "DONE",
                "message": "patched after repair",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main>Updated Portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError(
            "Patch apply error: Patch check failed: error: patch failed: index.html:90\n"
            "error: index.html: patch does not apply"
        )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Enhance navigation only",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Scoped nav enhancement",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert index_path.read_text(encoding="utf-8") == "<main>Updated Portfolio</main>\n"
    # Deterministic fallback applies locally after patch failure; no repair prompt required.
    assert len(client.prompts) == 1


@pytest.mark.anyio
async def test_code_frontend_patch_repair_survives_triple_parse_retry_for_static_scope(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Frontend patch drift parse retries", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="CODE_FRONTEND",
            status="QUEUED",
            executor="codex",
            payload={"target_files": ["index.html"]},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -90,4 +90,4 @@\n"
                            "-<main>Portfolio</main>\n"
                            "+<main>Updated Portfolio</main>\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            "{\"status\":\"DONE\",\"message\":\"repair",
            "{\"status\":\"DONE\",\"message\":\"repair",
            "{\"status\":\"DONE\",\"message\":\"repair",
            {
                "status": "DONE",
                "message": "patched after parse retries",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main>Updated Portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    def fake_apply_patch(self, patch: str):
        raise ValueError(
            "Patch apply error: Patch check failed: error: patch failed: index.html:90\n"
            "error: index.html: patch does not apply"
        )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.runtime.codex_executor.RepoTools.apply_patch", fake_apply_patch)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Enhance navigation only",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Scoped nav enhancement",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert index_path.read_text(encoding="utf-8") == "<main>Updated Portfolio</main>\n"
    # Deterministic fallback should avoid repeated parse-repair retries.
    assert len(client.prompts) == 1


@pytest.mark.anyio
async def test_fix_test_failure_retry_escalates_to_premium_model(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Fix failure escalation", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["index.html"],
                "related_files": ["test_index_html.py"],
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            "{\"status\":\"DONE\",\"message\":\"repair",
            {
                "status": "DONE",
                "message": "repair after retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='fixed'>Portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Fix the failing portfolio markup",
                    "expected_files": ["index.html", "test_index_html.py"],
                    "steps": [
                        {
                            "title": "Repair failing portfolio validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "FIX_TEST_FAILURE",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "class='fixed'" in index_path.read_text(encoding="utf-8")
    assert client.models == ["gpt-4.1-mini", "gpt-4.1"]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"

    async with db_session_factory() as session:
        ai_job = (
            await session.execute(select(AIJobRun).where(AIJobRun.run_id == run_id))
        ).scalars().one()

    assert ai_job.actual_cost_cents == pytest.approx(0.0065, rel=1e-6)


@pytest.mark.anyio
async def test_write_tests_patch_repair_parse_retry_escalates_to_premium_model(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<nav><a href='#home'>Home</a></nav>\n", encoding="utf-8")
    test_path = tmp_path / "test_index_html.py"
    test_path.write_text(
        "def test_index_html_exists():\n"
        "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
        "        assert '<nav>' in handle.read()\n",
        encoding="utf-8",
    )

    async with db_session_factory() as session:
        project = Project(name="Write tests repair escalation", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["test_index_html.py"],
                "related_files": ["index.html"],
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "first write tests patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "test_index_html.py",
                        "patch": (
                            "--- a/test_index_html.py\n"
                            "+++ b/test_index_html.py\n"
                            "@@ def test_index_html_exists():\n"
                            "+def test_index_html_nav_has_home_anchor():\n"
                            "+    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "+        assert \"href='#home'\" in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            "{\"status\":\"DONE\",\"message\":\"repair",
            {
                "status": "DONE",
                "message": "repair after retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            "def test_index_html_exists():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert '<nav>' in handle.read()\n"
                            "\n"
                            "def test_index_html_nav_has_home_anchor():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert \"href='#home'\" in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)
    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add tests for pink navigation styling",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add tests for pink navigation styling",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_nav_has_home_anchor" in test_path.read_text(encoding="utf-8")
    assert client.models == ["gpt-4.1-mini", "gpt-4.1-mini", "gpt-4.1"]
    assert "structured output retry 1" in client.prompts[2].lower()
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_write_tests_patch_repair_survives_double_parse_retry_before_success(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<nav><a href='#home'>Home</a></nav>\n", encoding="utf-8")
    test_path = tmp_path / "test_index_html.py"
    test_path.write_text(
        "def test_index_html_exists():\n"
        "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
        "        assert '<nav>' in handle.read()\n",
        encoding="utf-8",
    )

    async with db_session_factory() as session:
        project = Project(name="Write tests repair double retry", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="WRITE_TESTS",
            key="WRITE_TESTS",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["test_index_html.py"],
                "related_files": ["index.html"],
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "first write tests patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "test_index_html.py",
                        "patch": (
                            "--- a/test_index_html.py\n"
                            "+++ b/test_index_html.py\n"
                            "@@ def test_index_html_exists():\n"
                            "+def test_index_html_nav_has_home_anchor():\n"
                            "+    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "+        assert \"href='#home'\" in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
            "{\"status\":\"DONE\",\"message\":\"repair",
            "{\"status\":\"DONE\",\"message\":\"repair retry",
            {
                "status": "DONE",
                "message": "repair after second parser retry",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "test_index_html.py",
                        "content": (
                            "def test_index_html_exists():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert '<nav>' in handle.read()\n"
                            "\n"
                            "def test_index_html_nav_has_home_anchor():\n"
                            "    with open('index.html', 'r', encoding='utf-8') as handle:\n"
                            "        assert \"href='#home'\" in handle.read()\n"
                        ),
                    }
                ],
                "artifacts": [],
            },
        ]
    )

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)
    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Add tests for pink navigation styling",
                    "expected_files": ["test_index_html.py"],
                    "steps": [
                        {
                            "title": "Add tests for pink navigation styling",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "WRITE_TESTS",
                            "expected_files": ["test_index_html.py"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "test_index_html_nav_has_home_anchor" in test_path.read_text(encoding="utf-8")
    assert client.models == ["gpt-4.1-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-4.1"]
    assert "structured output retry 1" in client.prompts[2].lower()
    assert "structured output retry 2" in client.prompts[3].lower()
    assert client.max_tokens[2] > client.max_tokens[1]
    assert client.max_tokens[3] > client.max_tokens[2]
    assert result["payload"]["ai_attempt_tiers"] == ["tier_standard", "tier_premium"]
    assert result["payload"]["ai_effective_tier"] == "tier_premium"


@pytest.mark.anyio
async def test_codex_executor_stops_before_mutation_when_run_budget_is_exhausted(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    contract = build_execution_contract(
        run_summary={"target_files": ["index.html"]},
        architecture_profile=None,
        plan_snapshot={"expected_files": ["index.html"]},
    )
    contract.budget.max_cost_cents = 0.0001
    contract.budget.refresh()

    async with db_session_factory() as session:
        project = Project(name="Budget exhausted before apply", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={
                "plan_snapshot": {"expected_files": ["index.html"]},
                "execution_contract": contract.to_dict(),
            },
        )
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="CODE_FRONTEND",
            key="THEME_PORTFOLIO",
            status="QUEUED",
            executor="codex",
            payload={"target_file": "index.html"},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main class='theme-shell'>Rethemed portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            }
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Retheme the single-file portfolio",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Implement themed portfolio shell",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "CODE_FRONTEND",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
                execution_contract=contract,
            ),
        )

    assert result["status"] == "FAILED"
    assert result["message"] == "run_budget_exhausted"
    assert "Rethemed portfolio" not in index_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_codex_executor_uses_recovery_reserve_for_fix_items(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<main>Portfolio</main>\n", encoding="utf-8")

    contract = build_execution_contract(
        run_summary={"target_files": ["index.html"]},
        architecture_profile=None,
        plan_snapshot={"expected_files": ["index.html"]},
    )
    contract.budget.max_cost_cents = 0.0001
    contract.budget.recovery_reserve_cost_cents = 12.0
    contract.budget.refresh(recovery_mode=True)

    async with db_session_factory() as session:
        project = Project(name="Recovery reserve project", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(
            project_id=project.id,
            tenant_id=tenant_id,
            status="RUNNING",
            executor="codex",
            summary={
                "plan_snapshot": {"expected_files": ["index.html"]},
                "execution_contract": contract.to_dict(),
            },
        )
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE_1",
            status="QUEUED",
            executor="codex",
            payload={
                "target_files": ["index.html"],
                "expected_files": ["index.html"],
                "failed_work_item_id": str(uuid.uuid4()),
                "recovery_action": "spawn_fix_node",
                "recovery_tier": "code_repair",
            },
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequenceRawClient(
        [
            {
                "status": "DONE",
                "message": "patched",
                "warnings": [],
                "actions": [
                    {
                        "type": "write_file",
                        "path": "index.html",
                        "content": "<main>Recovered portfolio</main>\n",
                    }
                ],
                "artifacts": [],
            }
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)

    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={"goal": "Recover failed tests", "expected_files": ["index.html"]},
                repo_path=str(tmp_path),
                execution_contract=contract,
            ),
        )

    assert result["status"] == "DONE"
    assert "Recovered portfolio" in index_path.read_text(encoding="utf-8")
    assert client.models
    assert "mini" in str(client.models[0])


@pytest.mark.anyio
async def test_fix_test_failure_normalizes_failed_model_status_when_patch_applies(
    monkeypatch,
    db_session_factory,
    tmp_path,
):
    tenant_id = uuid.uuid4()
    index_path = tmp_path / "index.html"
    index_path.write_text("<header><h1>Portfolio</h1></header>\n", encoding="utf-8")

    async with db_session_factory() as session:
        project = Project(name="Fix failure normalization", tenant_id=tenant_id)
        session.add(project)
        await session.flush()

        run = Run(project_id=project.id, tenant_id=tenant_id, status="RUNNING", executor="codex")
        session.add(run)
        await session.flush()

        work_item = WorkItem(
            project_id=project.id,
            tenant_id=tenant_id,
            run_id=run.id,
            type="FIX_TEST_FAILURE",
            key="FIX_TEST_FAILURE",
            status="QUEUED",
            executor="codex",
            payload={"target_files": ["index.html"]},
        )
        session.add(work_item)
        await session.commit()
        project_id = project.id
        run_id = run.id
        work_item_id = work_item.id

    client = SequencePlanClient(
        [
            {
                "status": "FAILED",
                "message": "proposed a fix patch",
                "warnings": [],
                "actions": [
                    {
                        "type": "apply_patch",
                        "path": "index.html",
                        "patch": (
                            "--- a/index.html\n"
                            "+++ b/index.html\n"
                            "@@ -1 +1 @@\n"
                            "-<header><h1>Portfolio</h1></header>\n"
                            "+<section class=\"hero\"><header><h1>Portfolio</h1></header></section>\n"
                        ),
                    }
                ],
                "artifacts": [],
            }
        ]
    )

    monkeypatch.setattr("app.runtime.codex_executor.SessionLocal", db_session_factory)
    executor = CodexExecutor(repo_root=tmp_path)
    executor._job_manager = AIJobManager(session_factory=db_session_factory)
    monkeypatch.setattr(executor, "_get_client", lambda: client)

    async with db_session_factory() as session:
        work_item = await session.get(WorkItem, work_item_id)
        assert work_item is not None
        result = await executor.execute(
            work_item,
            RunContext(
                project_id=project_id,
                run_id=run_id,
                plan_snapshot={
                    "goal": "Fix the failing hero-section validation",
                    "expected_files": ["index.html"],
                    "steps": [
                        {
                            "title": "Fix failing hero validation",
                            "work_item_id": str(work_item_id),
                            "work_item_type": "FIX_TEST_FAILURE",
                            "expected_files": ["index.html"],
                        }
                    ],
                },
                repo_path=str(tmp_path),
            ),
        )

    assert result["status"] == "DONE"
    assert "candidate fix patch" in result["message"].lower()
    assert "fix_patch_applied_despite_failed_model_status" in result["payload"]["warnings"]
    assert "class=\"hero\"" in index_path.read_text(encoding="utf-8")


def test_frontend_writefile_violations_detect_root_monolith_output():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={"target_files": ["index.html"]},
    )
    dense_html = "<!doctype html>\n<html>\n" + ("<section>Block</section>\n" * 800) + "</html>\n"
    actions = [SimpleNamespace(type="write_file", path="index.html", content=dense_html)]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("structural contract violation" in violation for violation in violations)


def test_frontend_writefile_violations_require_governed_component_composition_for_large_root():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={"target_files": ["index.html"]},
    )
    large_root = "<!doctype html>\n<html>\n<body>\n" + ("<div>content</div>\n" * 220) + "</body>\n</html>\n"
    actions = [SimpleNamespace(type="write_file", path="index.html", content=large_root)]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("must compose from governed components" in violation for violation in violations)


def test_frontend_writefile_violations_detect_repeated_inline_sections_without_governed_components():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={"target_files": ["index.html"]},
    )
    repeated_sections = "<!doctype html>\n<html>\n<body>\n" + ("<section>Block</section>\n" * 8) + "</body>\n</html>\n"
    actions = [SimpleNamespace(type="write_file", path="index.html", content=repeated_sections)]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("repeated inline section patterns detected" in violation for violation in violations)


def test_frontend_materialization_blocks_empty_primary_button_for_hero_cta_task():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={
            "task_title": "Implement Hero Section with Primary CTA",
            "goal": "Implement hero section with call-to-action button",
            "target_files": ["index.html"],
        },
    )
    patch = (
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -10,1 +10,2 @@\n"
        "-  <PrimaryButton>Get Started</PrimaryButton>\n"
        "+  <PrimaryButton></PrimaryButton>\n"
        "+  <PrimaryButton tone=\"brand-primary\">Get Started</PrimaryButton>\n"
    )
    actions = [SimpleNamespace(type="apply_patch", path="index.html", patch=patch)]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("empty PrimaryButton" in violation for violation in violations)


def test_frontend_materialization_blocks_negligible_hero_cta_delta():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={
            "task_title": "Implement Hero Section with Primary CTA",
            "goal": "Implement hero section with primary cta",
            "target_files": ["index.html"],
        },
    )
    patch = (
        "--- a/index.html\n"
        "+++ b/index.html\n"
        "@@ -20,1 +20,1 @@\n"
        "-  <PrimaryButton tone=\"secondary\">Request Demo</PrimaryButton>\n"
        "+  <PrimaryButton tone=\"brand-accent\">Request Demo</PrimaryButton>\n"
    )
    actions = [SimpleNamespace(type="apply_patch", path="index.html", patch=patch)]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("negligible or non-perceptible UI delta" in violation for violation in violations)


def test_frontend_topology_rejects_non_governed_paths():
    actions = [SimpleNamespace(type="write_file", path="src/random/NewPanel.vue", content="<template><div /></template>")]
    violations = validate_frontend_topology(actions=actions, enforce=True)
    assert any("outside governed frontend folders" in violation for violation in violations)


def test_frontend_topology_rejects_root_single_file_dump():
    dumped = "<!doctype html>\\n<html><body>\\n" + ("<section style='color:red'>Block</section>\\n" * 10) + ("<style>.x{color:red;}</style>\\n" * 100) + "</body></html>"
    actions = [SimpleNamespace(type="write_file", path="index.html", content=dumped)]
    violations = validate_frontend_topology(actions=actions, enforce=True)
    assert any("single-file app dump" in violation for violation in violations)
    assert any("inline CSS dump patterns" in violation for violation in violations)


def test_component_capability_protocol_resolves_known_component():
    payload = resolve_component_capability("HeroSection", variant="premium_saas")
    assert payload["capability"] == "HeroSection"
    assert payload["variant"] == "premium_saas"
    assert "slots" in payload and "allowed_props" in payload


def test_frontend_instructions_include_component_capability_packet():
    executor = CodexExecutor(repo_root=Path.cwd())
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    work_item = WorkItem(
        id=uuid.uuid4(),
        run_id=run_id,
        project_id=project_id,
        tenant_id=uuid.uuid4(),
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={"target_files": ["index.html"], "component_variant": "premium_saas"},
    )
    context = RunContext(
        project_id=project_id,
        run_id=run_id,
        project_contract={
            "design_contract": {
                "experience_blueprint": "premium_saas",
                "allowed_components": ["HeroSection", "PricingCard", "UnknownThing"],
            }
        },
    )
    instructions = executor._instructions_for(work_item, context=context)
    assert "COMPONENT_CAPABILITY_PACKET" in instructions
    assert "HeroSection" in instructions
    assert "PricingCard" in instructions


def test_derive_frontend_topology_plan_for_static_root_scope():
    work_item = WorkItem(type="CODE_FRONTEND", status="QUEUED", payload={"target_files": ["index.html"]})
    plan = _derive_frontend_topology_plan(
        work_item=work_item,
        payload=work_item.payload,
        target_files=["index.html"],
    )
    assert isinstance(plan, dict)
    assert plan["planner_stage"] == "PLAN_FRONTEND_TOPOLOGY_V1"
    assert plan["root_file"] == "index.html"
    assert isinstance(plan.get("component_files"), list)
    assert any(str(path).endswith("HeroSection.vue") for path in plan["component_files"])


def test_static_frontend_scope_accepts_vite_entrypoint_ts():
    assert _is_static_frontend_scope({"target_files": ["apps/web/src/main.ts"]}) is True


def test_target_files_from_payload_canonicalizes_apps_web_entrypoint_scope():
    resolved = _target_files_from_payload(
        {
            "package_affinity": "apps/web",
            "target_files": ["src/main.ts", "index.html"],
        }
    )
    assert "apps/web/src/main.ts" in resolved
    assert "apps/web/index.html" in resolved
    assert "src/main.ts" not in resolved
    assert "index.html" not in resolved


def test_frontend_scope_sanitizer_drops_root_component_files():
    scoped = _sanitize_frontend_scope_paths(
        [
            "App.vue",
            "LandingPage.vue",
            "apps/web/src/pages/LandingPage.vue",
            "apps/web/src/main.ts",
        ]
    )
    assert "App.vue" not in scoped
    assert "LandingPage.vue" not in scoped
    assert "apps/web/src/pages/LandingPage.vue" in scoped
    assert "apps/web/src/main.ts" in scoped


def test_derive_frontend_topology_plan_for_vite_main_ts_scope():
    work_item = WorkItem(type="CODE_FRONTEND", status="QUEUED", payload={"target_files": ["apps/web/src/main.ts"]})
    plan = _derive_frontend_topology_plan(
        work_item=work_item,
        payload=work_item.payload,
        target_files=["apps/web/src/main.ts"],
    )
    assert isinstance(plan, dict)
    assert plan["root_file"] == "apps/web/src/main.ts"


def test_frontend_writefile_violations_require_planned_component_writes():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_FRONTEND",
        status="QUEUED",
        payload={
            "target_files": ["index.html"],
            "frontend_topology_plan": {
                "component_files": ["apps/web/src/components/landing/HeroSection.vue"],
            },
        },
    )
    dense_html = "<!doctype html>\n<html>\n" + ("<section>Block</section>\n" * 800) + "</html>\n"
    actions = [SimpleNamespace(type="write_file", path="index.html", content=dense_html)]
    violations = executor._frontend_writefile_violations(work_item=work_item, actions=actions)
    assert any("planned topology requires componentized output" in violation for violation in violations)


def test_derive_backend_topology_plan_for_root_backend_scope():
    work_item = WorkItem(type="CODE_BACKEND", status="QUEUED", payload={"target_files": ["app.py"]})
    plan = _derive_backend_topology_plan(
        work_item=work_item,
        payload=work_item.payload,
        target_files=["app.py"],
    )
    assert isinstance(plan, dict)
    assert plan["planner_stage"] == "PLAN_BACKEND_TOPOLOGY_V1"
    assert plan["entrypoint_file"] == "app.py"
    assert isinstance(plan.get("module_files"), dict)
    assert "routes" in plan["module_files"]


def test_backend_writefile_violations_require_planned_module_writes():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_BACKEND",
        status="QUEUED",
        payload={
            "target_files": ["app.py"],
            "backend_topology_plan": {
                "module_files": {
                    "routes": "apps/api/app/routes/lead_capture.py",
                    "services": "apps/api/app/services/lead_capture_service.py",
                }
            },
        },
    )
    dense_backend = "\n".join(["def route(): pass" for _ in range(320)]) + "\n"
    actions = [SimpleNamespace(type="write_file", path="app.py", content=dense_backend)]
    violations = executor._backend_writefile_violations(work_item=work_item, actions=actions)
    assert any("planned backend topology requires modular output" in violation for violation in violations)


def test_backend_instructions_include_topology_plan_details():
    executor = CodexExecutor(repo_root=Path.cwd())
    work_item = WorkItem(
        type="CODE_BACKEND",
        status="QUEUED",
        payload={
            "target_files": ["app.py"],
            "backend_topology_plan": {
                "entrypoint_file": "app.py",
                "module_files": {
                    "routes": "apps/api/app/routes/lead_capture.py",
                    "services": "apps/api/app/services/lead_capture_service.py",
                },
            },
        },
    )
    instructions = executor._instructions_for(work_item)
    assert "Backend topology plan is active" in instructions
    assert "lead_capture_service.py" in instructions
