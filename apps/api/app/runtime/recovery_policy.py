from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
import re
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Run, Trace, WorkItem, WorkItemEdge
from app.runtime.run_state import RetryState
from app.runtime.runtime_recovery_service import RuntimeRecoveryService
from app.services.event_log import record_event
from app.services.runtime_lineage import link_run_to_work_item


RECOVERY_TIER_BY_FAILURE_CLASS: dict[str, str] = {
    "clone_auth_failure": "deterministic",
    "environment_failure": "deterministic",
    "transient": "cheap_recovery",
    "syntax_failure": "code_repair",
    "dependency_failure": "code_repair",
    "test_assertion_failure": "code_repair",
    "test_failure": "code_repair",
    "policy_failure": "architectural_recovery",
    "multi_file_behavior_failure": "architectural_recovery",
    "missing_context": "architectural_recovery",
    "logic_failure": "architectural_recovery",
    "budget_exhausted": "deterministic",
    "fix_applied": "deterministic",
    "patch_apply_failure": "cheap_recovery",
    "output_contract_invalid": "cheap_recovery",
    "structural_contract_violation": "architectural_recovery",
    "stack_test_strategy_mismatch": "code_repair",
    "layout_composition_failure": "architectural_recovery",
    "zone_composition_failure": "architectural_recovery",
    "incomplete_zone_replacement": "architectural_recovery",
    "visual_quality_failure": "architectural_recovery",
    "frontend_syntax_failure": "code_repair",
    "mutation_authority_violation": "architectural_recovery",
    "foundation_bootstrap_required": "architectural_recovery",
}


class FrontendReadinessState(str, Enum):
    FOUNDATION_BROKEN = "FOUNDATION_BROKEN"
    TOPOLOGY_BROKEN = "TOPOLOGY_BROKEN"
    COMPOSITION_BROKEN = "COMPOSITION_BROKEN"
    LAYOUT_DEGRADED = "LAYOUT_DEGRADED"
    READY = "PREVIEW_READY"


def _frontend_readiness_state_from_error_text(text: str) -> FrontendReadinessState:
    lowered = str(text or "").lower()
    if any(
        token in lowered
        for token in (
            "run genesis_foundation repair before code_frontend",
            "landingpage missing required zone markers",
            "foundation prerequisite violation",
            "landingpage.vue does not exist",
            "patch could not be applied because apps/web/src/pages/landingpage.vue does not exist",
            "app.vue does not exist",
            "pageshell.vue does not exist",
            "vite.config",
            "package.json does not exist",
            "main.ts",
        )
    ):
        return FrontendReadinessState.FOUNDATION_BROKEN
    if any(
        token in lowered
        for token in (
            "foundation topology violation",
            "feature tasks may not create or replace isolated pages",
            "routing topology",
            "shell protection violation",
        )
    ):
        return FrontendReadinessState.TOPOLOGY_BROKEN
    if any(
        token in lowered
        for token in (
            "zone composition violation",
            "missing required zone markers",
            "replace_landing_page",
            "placeholder replacement violation",
            "incomplete zone replacement",
            "mutation authority violation",
        )
    ):
        return FrontendReadinessState.COMPOSITION_BROKEN
    if any(
        token in lowered
        for token in (
            "layout governance violation",
            "tailwind governance violation",
            "missing responsive container",
            "missing max-width/container utility",
            "potential overflow without overflow safety guard",
            "unbounded svg dimension",
            "oversized arbitrary dimension",
            "visual quality gate",
            "bounded_svg_icons",
            "no_overflow",
            "typography_hierarchy",
        )
    ):
        return FrontendReadinessState.LAYOUT_DEGRADED
    return FrontendReadinessState.READY


def _run_tests_failure_signature(item: WorkItem) -> str:
    result = item.result if isinstance(item.result, dict) else {}
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    message = str(result.get("message") or "")
    last_error = str(item.last_error or "")
    return "\n".join(
        part.strip().lower()
        for part in (
            stdout[:600],
            stderr[:300],
            message[:180],
            last_error[:180],
        )
        if part
    )


def _is_dependency_import_signature(signature: str) -> bool:
    text = str(signature or "").lower()
    return "no module named" in text or "modulenotfounderror" in text


@dataclass(frozen=True)
class RecoveryRule:
    when_status: str
    failure_class: str
    action: str
    spawn_type: str | None = None


RECOVERY_POLICIES: dict[str, dict[str, Any]] = {
    "CODE_FRONTEND": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "structural_contract_violation", "retry"),
            RecoveryRule("FAILED", "design_token_violation", "retry"),
            RecoveryRule("FAILED", "layout_composition_failure", "spawn_fix_node", "FIX_LAYOUT_COMPOSITION"),
            RecoveryRule("FAILED", "zone_composition_failure", "spawn_fix_node", "FIX_ZONE_COMPOSITION"),
            RecoveryRule("FAILED", "frontend_syntax_failure", "spawn_fix_node", "FIX_FRONTEND_SYNTAX"),
            RecoveryRule("FAILED", "visual_quality_failure", "spawn_fix_node", "FIX_VISUAL_QUALITY"),
            RecoveryRule("FAILED", "mutation_authority_violation", "spawn_fix_node", "FIX_ZONE_COMPOSITION"),
            RecoveryRule("FAILED", "foundation_bootstrap_required", "spawn_fix_node", "GENESIS_FOUNDATION"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "CODE_BACKEND": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "patch_size_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "GENERATE_ROUTE": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "patch_size_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "GENERATE_SERVICE": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "patch_size_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "GENERATE_REPOSITORY": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "patch_size_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "GENERATE_CAPABILITY_BINDING": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "patch_size_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "RUN_TESTS": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("FAILED", "transient", "retry"),
            RecoveryRule("FAILED", "stack_test_strategy_mismatch", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "syntax_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "dependency_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "test_assertion_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "test_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
        ),
    },
    "FRAMEWORK_VALIDATE": {
        "max_retries": 1,
        "rules": (
            RecoveryRule("FAILED", "transient", "retry"),
            RecoveryRule("FAILED", "frontend_syntax_failure", "spawn_fix_node", "FIX_FRONTEND_SYNTAX"),
            RecoveryRule("FAILED", "syntax_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "dependency_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "missing_context", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "logic_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
        ),
    },
    "FIX_TEST_FAILURE": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("DONE", "fix_applied", "spawn_retry_node", "RUN_TESTS"),
        ),
    },
    "FIX_LAYOUT_COMPOSITION": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("DONE", "fix_applied", "spawn_retry_node", "CODE_FRONTEND"),
            RecoveryRule("FAILED", "foundation_bootstrap_required", "spawn_fix_node", "GENESIS_FOUNDATION"),
        ),
    },
    "FIX_FRONTEND_SYNTAX": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("DONE", "fix_applied", "spawn_retry_node", "FRAMEWORK_VALIDATE"),
        ),
    },
    "REVIEW_DIFF": {
        "max_retries": 0,
        "rules": (
            RecoveryRule("FAILED", "policy_failure", "block_run"),
        ),
    },
}

RECOVERY_TERMINAL_STATUSES = {"QUEUED", "RUNNING", "CLAIMED"}
MAX_SAME_FAILURE_SIGNATURE_RETRIES = 2
BACKEND_MODULE_TYPES = {
    "GENERATE_ROUTE",
    "GENERATE_SERVICE",
    "GENERATE_REPOSITORY",
    "GENERATE_CAPABILITY_BINDING",
}


def _unique_paths(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


def _coerce_path_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return _unique_paths([item for item in value if isinstance(item, str) and item.strip()])


def _canonicalize_frontend_recovery_paths(paths: list[str]) -> list[str]:
    canonical: list[str] = []
    for raw in paths:
        path = str(raw or "").strip().replace("\\", "/")
        if not path:
            continue
        lowered = path.lower()
        if lowered == "index.html":
            path = "apps/web/index.html"
        elif lowered in {"landingpage.vue", "src/landingpage.vue"}:
            path = "apps/web/src/LandingPage.vue"
        elif lowered == "app.vue":
            path = "apps/web/src/App.vue"
        elif lowered.startswith("src/"):
            path = f"apps/web/{path}"
        canonical.append(path)
    return _unique_paths(canonical)


def _extract_frontend_paths_from_error_text(text: str) -> list[str]:
    raw = str(text or "")
    if not raw:
        return []
    candidates: list[str] = []
    for match in re.findall(r"(/[^\s:]+\.(?:vue|ts|tsx|js|jsx|css|scss|sass|html))(?::\d+(?::\d+)?)?", raw):
        candidates.append(match)
    for match in re.findall(r"\b(src/[^\s:]+\.(?:vue|ts|tsx|js|jsx|css|scss|sass|html))(?::\d+(?::\d+)?)?", raw):
        candidates.append(match)
    normalized: list[str] = []
    for candidate in candidates:
        cleaned = str(candidate).strip().replace("\\", "/")
        if not cleaned:
            continue
        marker = "/repo/"
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1]
        if cleaned.startswith("/"):
            continue
        normalized.append(cleaned)
    return _canonicalize_frontend_recovery_paths(_unique_paths(normalized))


def _backend_recovery_context(work_item: WorkItem) -> dict[str, Any] | None:
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    topology = payload.get("backend_topology_plan") if isinstance(payload.get("backend_topology_plan"), dict) else None
    if not isinstance(topology, dict):
        return None
    type_to_node = {
        "GENERATE_ROUTE": "route",
        "GENERATE_SERVICE": "service",
        "GENERATE_REPOSITORY": "repository",
        "GENERATE_CAPABILITY_BINDING": "capability_binding",
    }
    module_node = type_to_node.get(str(work_item.type or "").strip().upper())
    if not module_node:
        return None
    dependency_graph = topology.get("dependency_graph") if isinstance(topology.get("dependency_graph"), dict) else {}
    edge_hint: dict[str, Any] = {}
    if module_node == "route":
        edge_hint = {"edge": "route_to_service", "targets": list((dependency_graph.get("route_to_service") or {}).values())[0] if isinstance(dependency_graph.get("route_to_service"), dict) and dependency_graph.get("route_to_service") else []}
    elif module_node == "service":
        edge_hint = {
            "edge": "service_to_repository",
            "targets": list((dependency_graph.get("service_to_repository") or {}).values())[0] if isinstance(dependency_graph.get("service_to_repository"), dict) and dependency_graph.get("service_to_repository") else [],
            "capabilities": list((dependency_graph.get("service_to_capabilities") or {}).values())[0] if isinstance(dependency_graph.get("service_to_capabilities"), dict) and dependency_graph.get("service_to_capabilities") else [],
        }
    elif module_node == "repository":
        edge_hint = {"edge": "service_to_repository", "role": "dependency_target"}
    elif module_node == "capability_binding":
        edge_hint = {"edge": "service_to_capabilities", "role": "dependency_target"}
    return {
        "planner_stage": topology.get("planner_stage"),
        "module": topology.get("module"),
        "module_node": module_node,
        "work_item_type": work_item.type,
        "retry_scope": "module_only",
        "dependency_graph_edge": edge_hint,
    }


def _looks_like_test_path(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return False
    pure = PurePosixPath(normalized)
    name = pure.name.lower()
    return (
        any(part.lower() == "tests" for part in pure.parts)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _fix_recovery_scope(payload: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if not isinstance(payload, dict):
        return [], []
    implementation_files = _coerce_path_list(payload.get("related_files"))
    if not implementation_files:
        implementation_files = [
            path
            for path in _coerce_path_list(payload.get("expected_files"))
            if not _looks_like_test_path(path)
        ]
    failing_test_files = _coerce_path_list(payload.get("target_files"))
    if not failing_test_files:
        failing_test_files = [
            path
            for path in _coerce_path_list(payload.get("expected_files"))
            if _looks_like_test_path(path)
        ]
    normalized_impl = _canonicalize_frontend_recovery_paths(_unique_paths(implementation_files))
    failing_test_files = _canonicalize_frontend_recovery_paths(_unique_paths(failing_test_files))
    has_frontend_feature_component = any(
        path.replace("\\", "/").startswith("apps/web/src/components/") and path.endswith(".vue")
        for path in normalized_impl
    )
    if has_frontend_feature_component:
        # Preserve feature topology during recovery: do not hand page topology files to fix-recovery
        # when component composition already exists.
        normalized_impl = [
            path
            for path in normalized_impl
            if path.replace("\\", "/")
            not in {
                "apps/web/src/pages/LandingPage.vue",
                "apps/web/src/LandingPage.vue",
                "LandingPage.vue",
            }
        ]
    error_text = "\n".join(str(payload.get(key) or "") for key in ("stderr", "stdout", "message", "last_error"))
    inferred_from_errors = _extract_frontend_paths_from_error_text(error_text)
    if inferred_from_errors:
        normalized_impl = _unique_paths([*normalized_impl, *inferred_from_errors])
    return normalized_impl, _unique_paths(failing_test_files)


def _layout_composition_recovery_scope(payload: dict[str, Any] | None, *, repo_path: str | None = None) -> list[str]:
    """Constrain layout recovery to stable composition shell files.

    Layout repair should avoid section-level component files that may not exist yet
    (e.g. CTASection.vue) and instead operate on durable topology files.
    """

    if not isinstance(payload, dict):
        return ["apps/web/src/pages/LandingPage.vue"]

    candidates = _canonicalize_frontend_recovery_paths(
        _unique_paths(
            _coerce_path_list(payload.get("target_files"))
            + _coerce_path_list(payload.get("related_files"))
            + _coerce_path_list(payload.get("expected_files"))
        )
    )
    preferred_shell_files = [
        "apps/web/src/LandingPage.vue",
        "apps/web/src/pages/LandingPage.vue",
        "apps/web/src/layouts/PageShell.vue",
    ]
    allowed_shell_files = set(preferred_shell_files)
    scoped = [path for path in candidates if path.replace("\\", "/") in allowed_shell_files]
    if not scoped:
        scoped = preferred_shell_files.copy()

    repo_root = Path(repo_path).expanduser() if isinstance(repo_path, str) and repo_path.strip() else None
    if repo_root is not None:
        for candidate in preferred_shell_files:
            if (repo_root / candidate).exists():
                return [candidate]
    return _unique_paths(scoped[:1]) or ["apps/web/src/LandingPage.vue"]


def _error_text(work_item: WorkItem) -> str:
    bits = [
        work_item.last_error or "",
        str((work_item.result or {}).get("stderr") or ""),
        str((work_item.result or {}).get("stdout") or ""),
        str((work_item.result or {}).get("message") or ""),
    ]
    return "\n".join(bits).lower()


def _frontend_failure_signature(work_item: WorkItem) -> str:
    text = _error_text(work_item).strip().lower()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    return first_line[:220]


def recovery_tier_for_failure(failure_class: str) -> str:
    return RECOVERY_TIER_BY_FAILURE_CLASS.get(failure_class, "architectural_recovery")


def classify_failure(work_item: WorkItem) -> str:
    if work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"} and work_item.status == "DONE":
        return "fix_applied"
    if work_item.type == "REVIEW_DIFF" and work_item.status == "FAILED":
        return "policy_failure"

    text = _error_text(work_item)
    result = work_item.result if isinstance(work_item.result, dict) else {}
    if work_item.type == "RUN_TESTS" and bool(result.get("stack_mismatch_detected")):
        return "stack_test_strategy_mismatch"
    if "run_budget_exhausted" in text or "budget_exhausted" in text:
        return "budget_exhausted"
    if work_item.type in {"CODE_FRONTEND", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_VISUAL_QUALITY", "GENESIS_FOUNDATION", "FOUNDATION_VALIDATE"}:
        readiness_state = _frontend_readiness_state_from_error_text(text)
        if readiness_state == FrontendReadinessState.FOUNDATION_BROKEN:
            return "foundation_bootstrap_required"
        if readiness_state == FrontendReadinessState.TOPOLOGY_BROKEN:
            return "zone_composition_failure"
        if readiness_state == FrontendReadinessState.COMPOSITION_BROKEN:
            return "zone_composition_failure"
        if readiness_state == FrontendReadinessState.LAYOUT_DEGRADED:
            return "layout_composition_failure"
    if any(
        token in text
        for token in (
            "host key verification failed",
            "could not read from remote repository",
            "github runtime clone auth is unavailable",
            "repository not found",
            "permission denied (publickey)",
            "auth_mode=ssh",
            "auth_mode=github_app",
        )
    ):
        return "clone_auth_failure"
    if any(
        token in text
        for token in (
            "no such file or directory",
            "command not found",
            "executable not found",
            "could not resolve hostname",
        )
    ):
        return "environment_failure"
    if any(
        token in text
        for token in (
            "layout governance violation",
            "tailwind governance violation",
            "missing responsive container",
            "missing max-width/container utility",
            "potential overflow without overflow safety guard",
            "unbounded svg dimension",
            "oversized arbitrary dimension",
            "foundation topology violation",
            "placeholder replacement violation",
        )
    ):
        return "layout_composition_failure"
    if any(
        token in text
        for token in (
            "zone composition violation",
            "missing required zone markers",
            "replace_landing_page",
            "incomplete zone replacement",
        )
    ):
        return "zone_composition_failure"
    if any(
        token in text
        for token in (
            "visual quality gate",
            "bounded_svg_icons",
            "no_overflow",
            "typography_hierarchy",
        )
    ):
        return "visual_quality_failure"
    if "mutation authority violation" in text or "shell protection violation" in text:
        return "mutation_authority_violation"
    if work_item.type == "FRAMEWORK_VALIDATE" and work_item.status == "FAILED":
        if any(
            token in text
            for token in (
                "[plugin:vite:vue]",
                "[plugin:vite:import-analysis]",
                "vite:vue",
                "failed to resolve import",
                "attribute name cannot contain",
                "single file component can contain only one element",
                "unterminated string constant",
            )
        ):
            return "frontend_syntax_failure"
    if any(
        token in text
        for token in (
            "syntaxerror",
            "indentationerror",
            "nameerror",
            "importerror",
            "modulenotfounderror",
            "error collecting",
        )
    ):
        return "syntax_failure"
    if any(token in text for token in ("cannot import name", "no module named", "missing dependency")):
        return "dependency_failure"
    if any(token in text for token in ("timeout", "temporarily unavailable", "connection reset", "network")):
        return "transient"
    if "model_call_failed" in text:
        return "transient"
    if any(
        token in text
        for token in (
            "patch repair output was invalid",
            "output_contract_invalid",
            "unterminated string starting at",
        )
    ):
        return "output_contract_invalid"
    if "structural contract violation" in text:
        return "structural_contract_violation"
    if any(
        token in text
        for token in (
            "patch apply error",
            "patch apply failed",
            "patch check failed",
            "patch does not apply",
            "error: patch failed:",
            "corrupt patch",
            "patch fragment without header",
        )
    ):
        return "patch_apply_failure"
    if "patch too large for" in text:
        return "patch_size_violation"
    if "ad-hoc hex color" in text and "is not in token_registry.colors" in text:
        return "design_token_violation"
    if work_item.type == "RUN_TESTS" and work_item.status == "FAILED" and "failed " in text:
        return "test_assertion_failure"
    if work_item.type == "RUN_TESTS" and work_item.status == "FAILED":
        return "test_failure"
    if any(token in text for token in ("file not found", "missing document", "missing graph", "not found")):
        return "missing_context"
    return "logic_failure"


def plan_recovery(work_item: WorkItem, failure_class: str) -> RecoveryRule | None:
    policy = RECOVERY_POLICIES.get(work_item.type)
    if not policy:
        return None
    for rule in policy["rules"]:
        if rule.when_status == work_item.status and rule.failure_class == failure_class:
            return rule
    return None


def _merge_result_metadata(work_item: WorkItem, **updates: Any) -> None:
    payload = dict(work_item.result or {})
    payload.update({key: value for key, value in updates.items() if value is not None})
    work_item.result = payload


def _is_recovery_work_item(work_item: WorkItem) -> bool:
    if work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"}:
        return True
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    return any(key in payload for key in ("recovery_source_id", "failed_work_item_id", "recovery_action"))


def _next_same_signature_count(
    *,
    prior_signature: str,
    current_signature: str,
    prior_count: int,
) -> int:
    if not prior_signature or not current_signature or prior_signature != current_signature:
        return 0
    return max(0, int(prior_count)) + 1


async def has_pending_recovery_work(session: AsyncSession, run_id: uuid.UUID) -> bool:
    items = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == run_id,
                WorkItem.status.in_(list(RECOVERY_TERMINAL_STATUSES)),
            )
        )
    ).scalars().all()
    return any(_is_recovery_work_item(item) for item in items)


async def sync_run_recovery_latch(session: AsyncSession, run_id: uuid.UUID) -> bool:
    pending = await has_pending_recovery_work(session, run_id)
    run = await session.get(Run, run_id)
    if run is None:
        return pending
    summary = dict(run.summary or {})
    summary["recovery_in_progress"] = pending
    if not pending:
        summary["pending_recovery_count"] = 0
    run.summary = summary
    session.add(run)
    await session.flush()
    return pending


async def _emit_recovery_event(
    session: AsyncSession,
    work_item: WorkItem,
    *,
    failure_class: str,
    action: str,
    recovery_work_item_id: uuid.UUID | None = None,
    recovery_type: str | None = None,
    message: str | None = None,
) -> None:
    recovery_context = _backend_recovery_context(work_item)
    await record_event(
        session,
        project_id=work_item.project_id,
        run_id=work_item.run_id,
        work_item_id=work_item.id,
        event_type="WORK_ITEM_RECOVERY",
        actor_type="SYSTEM",
        message=message,
        payload={
            "work_item_id": str(work_item.id),
            "failure_class": failure_class,
            "recovery_tier": recovery_tier_for_failure(failure_class),
            "recovery_action": action,
            "recovery_work_item_id": str(recovery_work_item_id) if recovery_work_item_id else None,
            "recovery_type": recovery_type,
            "recovery_context": recovery_context,
        },
        tenant_id=work_item.tenant_id,
    )


async def _spawn_fix_node(session: AsyncSession, failed_work_item: WorkItem, failure_class: str) -> dict[str, Any] | None:
    settings = get_settings()
    count = (
        await session.execute(
            select(func.count()).where(
                WorkItem.run_id == failed_work_item.run_id,
                WorkItem.type.in_(["FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"]),
            )
        )
    ).scalar() or 0
    if count >= settings.max_fix_attempts_per_run:
        return None

    implementation_files, failing_test_files = _fix_recovery_scope(failed_work_item.payload or {})
    run = await session.get(Run, failed_work_item.run_id)
    if failure_class == "layout_composition_failure":
        implementation_files = _layout_composition_recovery_scope(
            failed_work_item.payload or {},
            repo_path=run.repo_path if run is not None else None,
        )
    fix_payload = {
        "test_exit_code": (failed_work_item.result or {}).get("exit_code"),
        "stdout": (failed_work_item.result or {}).get("stdout"),
        "stderr": (failed_work_item.result or {}).get("stderr"),
        "failed_work_item_id": str(failed_work_item.id),
        "failure_class": failure_class,
        "recovery_action": "spawn_fix_node",
        "recovery_tier": recovery_tier_for_failure(failure_class),
    }
    if failure_class == "stack_test_strategy_mismatch":
        run_test_result = failed_work_item.result if isinstance(failed_work_item.result, dict) else {}
        fix_payload["stack_mismatch_detected"] = True
        fix_payload["stack_mismatch_reason"] = run_test_result.get("stack_mismatch_reason")
        fix_payload["stack_mismatch_repairs"] = run_test_result.get("stack_mismatch_repairs") if isinstance(run_test_result.get("stack_mismatch_repairs"), list) else []
        fix_payload["test_strategy_before"] = run_test_result.get("test_strategy")
        fix_payload["test_strategy_after"] = "vitest"
        fix_payload["framework_router"] = "frontend_vite_vitest"
        fix_payload["recovery_action"] = "stack_mismatch_repair"
    if implementation_files:
        fix_payload["target_files"] = implementation_files
        fix_payload["files"] = implementation_files
        fix_payload["expected_files"] = implementation_files
    if failing_test_files:
        fix_payload["related_files"] = failing_test_files
        fix_payload["failing_test_files"] = failing_test_files

    spawn_type_map = {
        "layout_composition_failure": "FIX_LAYOUT_COMPOSITION",
        "zone_composition_failure": "FIX_ZONE_COMPOSITION",
        "frontend_syntax_failure": "FIX_FRONTEND_SYNTAX",
        "visual_quality_failure": "FIX_VISUAL_QUALITY",
        "mutation_authority_violation": "FIX_ZONE_COMPOSITION",
        "foundation_bootstrap_required": "GENESIS_FOUNDATION",
    }
    spawn_type = spawn_type_map.get(failure_class, "FIX_TEST_FAILURE")
    fix = WorkItem(
        project_id=failed_work_item.project_id,
        tenant_id=failed_work_item.tenant_id,
        run_id=failed_work_item.run_id,
        type=spawn_type,
        key=f"{spawn_type}_{count + 1}",
        status="QUEUED",
        executor="codex",
        priority=9,
        required_capabilities=["code"],
        payload=fix_payload,
    )
    session.add(fix)
    await session.flush()
    await link_run_to_work_item(session, fix)
    session.add(
        Trace(
            tenant_id=failed_work_item.tenant_id,
            project_id=failed_work_item.project_id,
            from_type="work_item",
            from_id=failed_work_item.id,
            to_type="work_item",
            to_id=fix.id,
            relation_type="supersedes",
            relation_strength=1.0,
        )
    )
    await record_event(
        session,
        project_id=fix.project_id,
        run_id=fix.run_id,
        work_item_id=fix.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(fix.id), "type": fix.type},
        tenant_id=fix.tenant_id,
    )
    await _emit_recovery_event(
        session,
        failed_work_item,
        failure_class=failure_class,
        action="spawn_fix_node",
        recovery_work_item_id=fix.id,
        recovery_type=fix.type,
        message=f"Auto recovery queued {fix.type} for failed {failed_work_item.type}.",
    )
    if run is not None:
        summary = dict(run.summary or {})
        summary["recovery_in_progress"] = True
        summary["pending_recovery_count"] = int(summary.get("pending_recovery_count") or 0) + 1
        run.summary = summary
        session.add(run)
        await session.flush()
    return {"work_item_id": fix.id, "type": fix.type}


async def _spawn_test_retry(session: AsyncSession, source_work_item: WorkItem) -> dict[str, Any] | None:
    failed_tests = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == source_work_item.run_id,
                WorkItem.type == "RUN_TESTS",
                WorkItem.status == "FAILED",
            )
        )
    ).scalars().all()
    if not failed_tests:
        return None

    latest_failed = max(
        failed_tests,
        key=lambda item: item.created_at,
    )
    signature = _run_tests_failure_signature(latest_failed)
    retry_cap = max(1, int(get_settings().runtime_test_retry_max_per_signature))
    if signature and _is_dependency_import_signature(signature):
        # Dependency import errors often persist inside the same runtime environment
        # even after requirements files are patched. Limit auto-retry churn.
        retry_cap = min(retry_cap, 1)
    prior_same_signature_retries = 0
    if signature:
        prior_same_signature_retries = sum(
            1
            for item in failed_tests
            if isinstance(item.payload, dict)
            and str(item.payload.get("recovery_action") or "") == "spawn_retry_node"
            and str(item.payload.get("recovery_retry_signature") or "") == signature
        )
        if prior_same_signature_retries >= retry_cap:
            await record_event(
                session,
                project_id=source_work_item.project_id,
                run_id=source_work_item.run_id,
                work_item_id=source_work_item.id,
                event_type="RUN_CONVERGENCE_STOPPED",
                actor_type="SYSTEM",
                tenant_id=source_work_item.tenant_id,
                payload={
                    "work_item_id": str(source_work_item.id),
                    "reason": "test_retry_signature_cap_reached",
                    "failure_signature": signature,
                    "retry_cap": retry_cap,
                },
                message="Recovery halted: identical RUN_TESTS failure signature reached retry cap.",
            )
            return None

    retry_payload = dict(latest_failed.payload or {})
    retry_payload.update(
        {
            "recovery_source_id": str(source_work_item.id),
            "recovery_action": "spawn_retry_node",
            "recovery_retry_signature": signature,
            "recovery_retry_count": prior_same_signature_retries + 1,
        }
    )
    test = WorkItem(
        project_id=source_work_item.project_id,
        tenant_id=source_work_item.tenant_id,
        run_id=source_work_item.run_id,
        type="RUN_TESTS",
        key=f"RUN_TESTS_{uuid.uuid4().hex[:4]}",
        status="QUEUED",
        executor="test",
        priority=8,
        required_capabilities=["test"],
        payload=retry_payload,
        depends_on_count=1,
    )
    session.add(test)
    await session.flush()
    await link_run_to_work_item(session, test)
    session.add(
        WorkItemEdge(
            tenant_id=source_work_item.tenant_id,
            run_id=source_work_item.run_id,
            from_work_item_id=source_work_item.id,
            to_work_item_id=test.id,
        )
    )

    for failed in failed_tests:
        outgoing_edges = (
            await session.execute(
                select(WorkItemEdge).where(
                    WorkItemEdge.run_id == failed.run_id,
                    WorkItemEdge.from_work_item_id == failed.id,
                )
            )
        ).scalars().all()
        failed_result = dict(failed.result or {})
        failed_result["superseded"] = True
        failed_result["superseded_by"] = str(test.id)
        failed.result = failed_result
        session.add(failed)
        for edge in outgoing_edges:
            edge.from_work_item_id = test.id
            session.add(edge)
        session.add(
            Trace(
                tenant_id=failed.tenant_id,
                project_id=failed.project_id,
                from_type="work_item",
                from_id=failed.id,
                to_type="work_item",
                to_id=test.id,
                relation_type="supersedes",
                relation_strength=1.0,
            )
        )

    session.add(
        Trace(
            tenant_id=source_work_item.tenant_id,
            project_id=source_work_item.project_id,
            from_type="work_item",
            from_id=source_work_item.id,
            to_type="work_item",
            to_id=test.id,
            relation_type="references",
            relation_strength=1.0,
        )
    )
    await record_event(
        session,
        project_id=test.project_id,
        run_id=test.run_id,
        work_item_id=test.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(test.id), "type": test.type},
        tenant_id=test.tenant_id,
    )
    await _emit_recovery_event(
        session,
        source_work_item,
        failure_class="fix_applied",
        action="spawn_retry_node",
        recovery_work_item_id=test.id,
        recovery_type=test.type,
        message=f"Recovery queued {test.type} retry after {source_work_item.type}.",
    )
    run = await session.get(Run, source_work_item.run_id)
    if run is not None:
        summary = dict(run.summary or {})
        summary["recovery_in_progress"] = True
        summary["pending_recovery_count"] = int(summary.get("pending_recovery_count") or 0) + 1
        run.summary = summary
        session.add(run)
        await session.flush()
    return {"work_item_id": test.id, "type": test.type}


async def _spawn_framework_validate_retry(session: AsyncSession, source_work_item: WorkItem) -> dict[str, Any] | None:
    payload = source_work_item.payload if isinstance(source_work_item.payload, dict) else {}
    failed_id_raw = str(payload.get("failed_work_item_id") or "").strip()
    if not failed_id_raw:
        return None
    try:
        failed_id = uuid.UUID(failed_id_raw)
    except ValueError:
        return None

    failed_item = await session.get(WorkItem, failed_id)
    if failed_item is None or failed_item.run_id != source_work_item.run_id:
        return None
    if failed_item.type != "FRAMEWORK_VALIDATE" or failed_item.status != "FAILED":
        return None

    existing_retry = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == source_work_item.run_id,
                WorkItem.type == "FRAMEWORK_VALIDATE",
                WorkItem.status.in_(["QUEUED", "RUNNING", "CLAIMED", "DONE"]),
                WorkItem.payload["recovery_source_id"].as_string() == str(source_work_item.id),
            )
        )
    ).scalars().first()
    if existing_retry is not None:
        return {"work_item_id": existing_retry.id, "type": existing_retry.type}

    retry_payload = dict(failed_item.payload or {})
    retry_payload.update(
        {
            "recovery_source_id": str(source_work_item.id),
            "recovery_action": "spawn_retry_node",
            "failed_work_item_id": str(failed_item.id),
        }
    )
    retry = WorkItem(
        project_id=source_work_item.project_id,
        tenant_id=source_work_item.tenant_id,
        run_id=source_work_item.run_id,
        type="FRAMEWORK_VALIDATE",
        key=f"{failed_item.key or failed_item.type}_RECOVERY_{uuid.uuid4().hex[:4]}",
        status="QUEUED",
        executor=failed_item.executor or "test",
        priority=max(int(failed_item.priority or 8), 8),
        required_capabilities=list(failed_item.required_capabilities or ["test"]),
        payload=retry_payload,
        depends_on_count=1,
    )
    session.add(retry)
    await session.flush()
    await link_run_to_work_item(session, retry)

    session.add(
        WorkItemEdge(
            tenant_id=source_work_item.tenant_id,
            run_id=source_work_item.run_id,
            from_work_item_id=source_work_item.id,
            to_work_item_id=retry.id,
        )
    )

    outgoing_edges = (
        await session.execute(
            select(WorkItemEdge).where(
                WorkItemEdge.run_id == failed_item.run_id,
                WorkItemEdge.from_work_item_id == failed_item.id,
            )
        )
    ).scalars().all()
    for edge in outgoing_edges:
        edge.from_work_item_id = retry.id
        session.add(edge)

    failed_result = dict(failed_item.result or {})
    failed_result["superseded"] = True
    failed_result["superseded_by"] = str(retry.id)
    failed_result["superseded_reason"] = "framework_validate_retry_spawned"
    failed_item.result = failed_result
    session.add(failed_item)

    session.add(
        Trace(
            tenant_id=failed_item.tenant_id,
            project_id=failed_item.project_id,
            from_type="work_item",
            from_id=failed_item.id,
            to_type="work_item",
            to_id=retry.id,
            relation_type="supersedes",
            relation_strength=1.0,
        )
    )
    await record_event(
        session,
        project_id=retry.project_id,
        run_id=retry.run_id,
        work_item_id=retry.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(retry.id), "type": retry.type},
        tenant_id=retry.tenant_id,
    )
    await _emit_recovery_event(
        session,
        source_work_item,
        failure_class="fix_applied",
        action="spawn_retry_node",
        recovery_work_item_id=retry.id,
        recovery_type=retry.type,
        message=f"Recovery queued {retry.type} retry after {source_work_item.type}.",
    )
    return {"work_item_id": retry.id, "type": retry.type}


async def _spawn_code_frontend_retry(session: AsyncSession, source_work_item: WorkItem) -> dict[str, Any] | None:
    payload = source_work_item.payload if isinstance(source_work_item.payload, dict) else {}
    failed_id_raw = str(payload.get("failed_work_item_id") or "").strip()
    if not failed_id_raw:
        return None
    try:
        failed_id = uuid.UUID(failed_id_raw)
    except ValueError:
        return None

    failed_item = await session.get(WorkItem, failed_id)
    if failed_item is None or failed_item.run_id != source_work_item.run_id:
        return None
    if failed_item.type != "CODE_FRONTEND" or failed_item.status != "FAILED":
        return None

    existing_retry = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == source_work_item.run_id,
                WorkItem.type == "CODE_FRONTEND",
                WorkItem.status.in_(["QUEUED", "RUNNING", "CLAIMED", "DONE"]),
                WorkItem.payload["recovery_source_id"].as_string() == str(source_work_item.id),
            )
        )
    ).scalars().first()
    if existing_retry is not None:
        return {"work_item_id": existing_retry.id, "type": existing_retry.type}

    retry_payload = dict(failed_item.payload or {})
    signature = _frontend_failure_signature(failed_item)
    prior_signature_retries = 0
    if signature:
        prior_signature_retries = (
            await session.execute(
                select(func.count()).where(
                    WorkItem.run_id == source_work_item.run_id,
                    WorkItem.type == "CODE_FRONTEND",
                    WorkItem.payload["recovery_failure_signature"].as_string() == signature,
                )
            )
        ).scalar() or 0
    retry_payload.update(
        {
            "recovery_source_id": str(source_work_item.id),
            "recovery_action": "spawn_retry_node",
            "failed_work_item_id": str(failed_item.id),
            "recovery_strategy": "layout_composition_repair",
            "recovery_failure_signature": signature,
            "recovery_same_failure_count": int(prior_signature_retries) + 1,
        }
    )
    if prior_signature_retries >= 1:
        retry_payload["recovery_strategy"] = "write_file_preferred"
        retry_payload["layout_auto_normalize"] = True
        retry_payload["recovery_escalation"] = "deterministic_overflow_repair"
    retry = WorkItem(
        project_id=source_work_item.project_id,
        tenant_id=source_work_item.tenant_id,
        run_id=source_work_item.run_id,
        type="CODE_FRONTEND",
        key=f"{failed_item.key or failed_item.type}_RECOVERY_{uuid.uuid4().hex[:4]}",
        status="QUEUED",
        executor=failed_item.executor or "codex",
        priority=max(int(failed_item.priority or 8), 8),
        required_capabilities=list(failed_item.required_capabilities or ["code"]),
        payload=retry_payload,
        depends_on_count=1,
    )
    session.add(retry)
    await session.flush()
    await link_run_to_work_item(session, retry)

    session.add(
        WorkItemEdge(
            tenant_id=source_work_item.tenant_id,
            run_id=source_work_item.run_id,
            from_work_item_id=source_work_item.id,
            to_work_item_id=retry.id,
        )
    )
    outgoing_edges = (
        await session.execute(
            select(WorkItemEdge).where(
                WorkItemEdge.run_id == failed_item.run_id,
                WorkItemEdge.from_work_item_id == failed_item.id,
            )
        )
    ).scalars().all()
    for edge in outgoing_edges:
        edge.from_work_item_id = retry.id
        session.add(edge)

    failed_result = dict(failed_item.result or {})
    failed_result["superseded"] = True
    failed_result["superseded_by"] = str(retry.id)
    failed_result["superseded_reason"] = "code_frontend_retry_spawned"
    failed_item.result = failed_result
    session.add(failed_item)
    return {"work_item_id": retry.id, "type": retry.type}


async def maybe_apply_recovery(session: AsyncSession, work_item: WorkItem) -> dict[str, Any] | None:
    runtime_recovery = RuntimeRecoveryService(session)
    failure_class = classify_failure(work_item)
    rule = plan_recovery(work_item, failure_class)
    if not rule:
        return None
    stable_failure_type = runtime_recovery.classify_failure_type(failure_class)
    run = await session.get(Run, work_item.run_id)
    if run is None:
        return None

    await runtime_recovery.emit_classified_event(work_item, stable_failure_type)
    prior_attempts = int(work_item.result.get("recovery_attempts", 0)) if isinstance(work_item.result, dict) else 0
    recovery_action, failure_signature = await runtime_recovery.select_recovery_action_with_memory(
        work_item,
        rule_action=rule.action,
        failure_type=stable_failure_type,
        attempt_number=prior_attempts + 1,
    )
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    repository_state = str(payload.get("repository_state") or "").strip().upper()
    if (
        failure_class == "patch_size_violation"
        and repository_state in {"GENESIS", "EARLY_BUILD"}
    ):
        recovery_action = "retry_with_write_file"
    prior_signature = str((work_item.result or {}).get("failure_signature") or "") if isinstance(work_item.result, dict) else ""
    prior_signature_count = int((work_item.result or {}).get("same_failure_signature_count") or 0) if isinstance(work_item.result, dict) else 0
    same_signature_count = _next_same_signature_count(
        prior_signature=prior_signature,
        current_signature=failure_signature,
        prior_count=prior_signature_count,
    )
    if prior_attempts >= 1 and prior_signature and prior_signature == failure_signature:
        switched_action: str | None = None
        if failure_signature.startswith("validation_drift:design_token_missing:"):
            switched_action = "retry_with_design_token_normalization"
        elif failure_signature.startswith("validation_drift:frontend_topology_inline_css:"):
            switched_action = "retry_with_design_token_normalization"
        elif failure_signature.startswith("scope_violation:patch_too_large:"):
            switched_action = "retry_with_write_file"
        if switched_action and switched_action != recovery_action:
            recovery_action = switched_action
            await record_event(
                session,
                project_id=work_item.project_id,
                run_id=work_item.run_id,
                work_item_id=work_item.id,
                event_type="RUN_CONVERGENCE_STRATEGY_SWITCHED",
                actor_type="SYSTEM",
                tenant_id=work_item.tenant_id,
                payload={
                    "work_item_id": str(work_item.id),
                    "failure_signature": failure_signature,
                    "previous_action": rule.action,
                    "new_action": recovery_action,
                    "reason": "repeated_failure_signature",
                },
            )
    allow_extended_frontend_topology_retries = failure_signature.startswith(
        "validation_drift:frontend_topology_inline_css:"
    )
    if same_signature_count >= MAX_SAME_FAILURE_SIGNATURE_RETRIES and not allow_extended_frontend_topology_retries:
        _merge_result_metadata(
            work_item,
            failure_class=failure_class,
            failure_type=stable_failure_type,
            recovery_action="escalate_to_human",
            failure_signature=failure_signature,
            same_failure_signature_count=same_signature_count,
            retry_state=RetryState.EXHAUSTED,
            recovery_exhausted_reason="repeated_failure_signature",
            suggested_next_action="Adjust scope, contract/tokens, or strategy before rerunning.",
        )
        session.add(work_item)
        await session.flush()
        await record_event(
            session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RUN_CONVERGENCE_STOPPED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={
                "work_item_id": str(work_item.id),
                "failure_signature": failure_signature,
                "same_failure_signature_count": same_signature_count,
                "threshold": MAX_SAME_FAILURE_SIGNATURE_RETRIES,
                "reason": "repeated_failure_signature",
            },
            message="Recovery halted: repeated identical failure signature exceeded convergence threshold.",
        )
        await runtime_recovery.emit_escalated_event(work_item, reason="repeated_failure_signature")
        await sync_run_recovery_latch(session, work_item.run_id)
        return {"action": "escalate_to_human", "reason": "repeated_failure_signature"}
    await runtime_recovery.emit_action_selected_event(work_item, recovery_action)
    budget_decision = await runtime_recovery.check_budget(run, work_item, stable_failure_type)
    if not budget_decision.allowed:
        _merge_result_metadata(
            work_item,
            failure_class=failure_class,
            failure_type=stable_failure_type,
            recovery_action="escalate_to_human",
            failure_signature=failure_signature,
            same_failure_signature_count=same_signature_count,
            retry_state=RetryState.EXHAUSTED,
            recovery_exhausted_reason=budget_decision.reason,
            suggested_next_action="Review failure evidence and continue manually.",
        )
        session.add(work_item)
        await session.flush()
        await runtime_recovery.emit_escalated_event(work_item, reason=f"recovery_budget_exhausted:{budget_decision.reason}")
        return {"action": "escalate_to_human", "reason": budget_decision.reason}

    _merge_result_metadata(
        work_item,
        failure_class=failure_class,
        failure_type=stable_failure_type,
        failure_signature=failure_signature,
        recovery_action=recovery_action,
        recovery_tier=recovery_tier_for_failure(failure_class),
        retry_state="PENDING",
        recovery_attempts=prior_attempts + 1,
        same_failure_signature_count=same_signature_count,
    )
    session.add(work_item)
    await session.flush()
    recovery_attempt = await runtime_recovery.create_attempt(
        run=run,
        work_item=work_item,
        failure_type=stable_failure_type,
        recovery_action=recovery_action,
        rationale=f"class={failure_class}, rule={rule.action}",
    )

    outcome: dict[str, Any] | None = None
    if rule.action == "retry":
        if work_item.attempt + 1 >= work_item.max_attempts:
            _merge_result_metadata(work_item, retry_state=RetryState.EXHAUSTED)
            session.add(work_item)
            await session.flush()
        else:
            payload = dict(work_item.payload or {})
            if failure_class == "output_contract_invalid":
                payload["strict_output_contract_mode"] = True
                payload["prior_output_contract_failures"] = int(payload.get("prior_output_contract_failures") or 0) + 1
            if failure_class == "structural_contract_violation":
                payload["strict_output_contract_mode"] = True
                payload["prior_output_contract_failures"] = int(payload.get("prior_output_contract_failures") or 0) + 1
                payload["componentization_repair_attempts"] = int(payload.get("componentization_repair_attempts") or 0) + 1
            payload["recovery_action"] = recovery_action
            if failure_class == "structural_contract_violation":
                payload["recovery_strategy"] = "componentization_repair"
                payload["recovery_reason"] = "structural_contract_violation"
            elif recovery_action == "retry_with_write_file":
                payload["recovery_strategy"] = "write_file_preferred"
                payload["recovery_reason"] = "patch_apply_failed"
            elif recovery_action == "retry_with_smaller_patch":
                payload["recovery_strategy"] = "minimal_patch_preferred"
                payload["recovery_reason"] = "patch_apply_failed"
            elif recovery_action == "retry_with_design_token_normalization":
                payload["recovery_strategy"] = "design_token_auto_normalize"
                payload["recovery_reason"] = "design_token_missing"
            elif recovery_action == "refresh_context":
                payload["recovery_strategy"] = "refresh_context"
            work_item.payload = payload
            work_item.status = "QUEUED"
            work_item.attempt += 1
            work_item.assigned_agent_id = None
            work_item.lease_expires_at = None
            work_item.finished_at = None
            _merge_result_metadata(work_item, retry_state=RetryState.PENDING)
            session.add(work_item)
            await session.flush()
            await record_event(
                session,
                project_id=work_item.project_id,
                run_id=work_item.run_id,
                work_item_id=work_item.id,
                event_type="WORK_ITEM_RETRIED",
                actor_type="SYSTEM",
                payload={
                    "work_item_id": str(work_item.id),
                    "attempt": work_item.attempt,
                    "recovery_context": _backend_recovery_context(work_item),
                },
                tenant_id=work_item.tenant_id,
            )
            await _emit_recovery_event(
                session,
                work_item,
                failure_class=failure_class,
                action="retry",
                message=f"Retry queued for {work_item.type} after transient failure.",
            )
            if recovery_action == "retry_with_write_file":
                await record_event(
                    session,
                    project_id=work_item.project_id,
                    run_id=work_item.run_id,
                    work_item_id=work_item.id,
                    event_type="PATCH_STRATEGY_SWITCHED_TO_WRITE_FILE",
                    actor_type="SYSTEM",
                    tenant_id=work_item.tenant_id,
                    payload={"work_item_id": str(work_item.id), "reason": "patch_apply_failed"},
                )
            outcome = {"action": "retry", "work_item_id": work_item.id}

    elif rule.action == "spawn_fix_node":
        _merge_result_metadata(work_item, retry_state=RetryState.PENDING)
        session.add(work_item)
        await session.flush()
        created = await _spawn_fix_node(session, work_item, failure_class)
        outcome = {"action": rule.action, "created": created}

    elif rule.action == "spawn_retry_node":
        _merge_result_metadata(work_item, retry_state=RetryState.PENDING)
        session.add(work_item)
        await session.flush()
        created: dict[str, Any] | None
        if work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_FRONTEND_SYNTAX"}:
            fix_payload = work_item.payload if isinstance(work_item.payload, dict) else {}
            failed_id_raw = str(fix_payload.get("failed_work_item_id") or "").strip()
            failed_item: WorkItem | None = None
            if failed_id_raw:
                try:
                    failed_item = await session.get(WorkItem, uuid.UUID(failed_id_raw))
                except ValueError:
                    failed_item = None
            if failed_item is not None and failed_item.type == "FRAMEWORK_VALIDATE":
                created = await _spawn_framework_validate_retry(session, work_item)
            elif failed_item is not None and failed_item.type == "CODE_FRONTEND":
                created = await _spawn_code_frontend_retry(session, work_item)
            else:
                created = await _spawn_test_retry(session, work_item)
        else:
            created = await _spawn_test_retry(session, work_item)
        outcome = {"action": rule.action, "created": created}

    elif rule.action == "block_run":
        _merge_result_metadata(work_item, retry_state=RetryState.BLOCKED)
        session.add(work_item)
        await session.flush()
        await _emit_recovery_event(
            session,
            work_item,
            failure_class=failure_class,
            action="block_run",
            message=f"{work_item.type} requires manual review; auto-healing blocked.",
        )
        outcome = {"action": "block_run"}

    succeeded = bool(outcome and (outcome.get("action") != "block_run"))
    if succeeded and outcome and outcome.get("action") in {"spawn_fix_node", "spawn_retry_node"}:
        succeeded = outcome.get("created") is not None
    await runtime_recovery.complete_attempt(
        recovery_attempt,
        succeeded=succeeded,
        rationale=(None if succeeded else "No automatic recovery outcome produced."),
    )
    await runtime_recovery.record_memory_outcome(
        work_item=work_item,
        failure_type=stable_failure_type,
        failure_signature=failure_signature,
        recovery_action=recovery_action,
        succeeded=succeeded,
        attempt_number=recovery_attempt.attempt_number,
    )
    await runtime_recovery.emit_attempt_terminal_event(work_item, recovery_attempt, succeeded=succeeded)
    if not succeeded:
        await runtime_recovery.emit_escalated_event(work_item, reason="recovery_action_not_effective")

    await sync_run_recovery_latch(session, work_item.run_id)
    return outcome
