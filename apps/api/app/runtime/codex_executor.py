from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any
import re

from app.db.models import Run, WorkItem
from app.db.session import SessionLocal
from app.runtime.executor import TaskExecutor, TaskResult
from app.runtime.context import RunContext
from app.runtime.execution_contract import ExecutionContract, is_recovery_work_item, record_run_budget_usage
from app.runtime.patch_guard import (
    DEFAULT_MAX_PATCH_FILES,
    HARD_MAX_PATCH_FILES,
    build_patch_guard_meta,
    derive_allowed_files,
    evaluate_project_contract_precheck,
    evaluate_patch_guard,
    has_mutating_actions,
)
from app.runtime.schemas.executor_io import Action, CodexPlan
from app.runtime.llm.openai_client import OpenAIClient
from app.runtime.tools.repo_tools import RepoTools
from app.core.config import get_settings
from app.schemas.run_narrative import RunPatchVerificationFinding, RunPatchVerificationSummary
from app.services.patch_verification import build_run_patch_plan_and_verification
from app.services.graph_context import EXECUTOR_CONTEXT_LIMITS, build_graph_context, compact_graph_context
from app.services.workspace_supervisor import workspace_uri
from app.services.ai_policy import AIJobManager, AIJobRequest, TIER_ORDER, contains_sensitive_paths, estimate_tokens, is_retryable_error, retry_error_kind
from app.services.event_log import record_event
from app.runtime.content_binding import (
    extract_literals,
    build_binding_registry,
    rewrite_with_content_slots,
    validate_binding_rewrite,
)
from app.services.content_registry import upsert_content_item
from app.runtime.frontend_topology import validate_frontend_topology
from app.runtime.frontend_topology_engine import (
    DEFAULT_LANDING_TOPOLOGY,
    FrontendTopology,
    FrontendZone,
    normalize_landing_graph_content,
)
from app.runtime.frontend_import_resolver import (
    normalize_frontend_imports,
)
from app.runtime.frontend_composition_governance import (
    evaluate_frontend_composition_governance,
    evaluate_frontend_foundation_governance,
)
from app.runtime.component_capability_protocol import build_component_capability_packet
from app.runtime.mutation_governance import MutationGovernanceDecision, evaluate_mutation_governance
from app.services.repo_intelligence_graph import get_safe_mutation_scope
from app.services.frontend_composition_integrity import ensure_frontend_foundation_files


SYSTEM_PROMPT = """You are an automated code change worker.
You must output ONLY a valid JSON object matching the provided schema.
Prefer apply_patch with unified diff (git format) for edits; use write_file for new files or full replacements.
If you use apply_patch, include full file headers such as --- a/path and +++ b/path before each hunk.
If you use apply_patch, every hunk header must use exact unified diff line numbers like @@ -10,2 +10,6 @@.
Never use placeholder hunk headers such as @@ ... @@.
Never return a hunk-only patch fragment that starts with @@ before file headers.
Do not invent files outside the repo. Do not include explanations outside JSON."""

REVIEW_SYSTEM_PROMPT = """You are an automated code review worker.
You must output ONLY a valid JSON object matching the provided schema.
This is a review stage, not an implementation stage.
Return only note actions with concise review findings, approval guidance, risks, or follow-up recommendations.
Never emit apply_patch, write_file, or delete_file actions.
Do not reproduce full diffs or file contents.
Do not invent files outside the repo. Do not include explanations outside JSON."""

STRUCTURED_OUTPUT_RETRY_LIMIT = 1
REPAIR_STRUCTURED_OUTPUT_RETRY_LIMIT = 2
MAX_FRONTEND_WRITE_FILE_BYTES = 24_000
MAX_FRONTEND_ROOT_MONOLITH_BYTES = 12_000
MAX_FRONTEND_ROOT_MONOLITH_LINES = 260
MUTATION_STRATEGIES = {"apply_patch", "write_file", "structured_transform", "component_replace", "multi_phase_patch"}
LAYOUT_SENSITIVE_HINTS = {
    "nav",
    "navbar",
    "header",
    "hero",
    "landing",
    "homepage",
    "home page",
    "layout",
    "responsive",
    "footer",
}
EXECUTION_ZONES = {"layout_zone", "logic_zone", "config_zone", "schema_zone", "infrastructure_zone"}
ADJACENT_REPAIR_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "vite.config.ts",
    "vite.config.js",
    "docker-compose.yml",
    ".env.example",
}

log = logging.getLogger("app.runtime.codex_executor")
_UNIFIED_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$")
_JSON_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL | re.IGNORECASE)
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_STYLE_ATTR_RE = re.compile(r"\bstyle\s*=", re.IGNORECASE)
_INLINE_STYLE_ATTR_RE = re.compile(r"\sstyle\s*=\s*\"[^\"]*\"|\sstyle\s*=\s*'[^']*'", re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_COMPONENT_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")
_CONTENT_SLOT_TAG_RE = re.compile(r"<ContentSlot\b([^>]*)\/>", re.IGNORECASE)
_SLOT_FALLBACK_BOUND_RE = re.compile(r':fallback\s*=\s*"([^"]*)"')
_SLOT_FALLBACK_LITERAL_RE = re.compile(r'fallback\s*=\s*"([^"]*)"')
_TAG_WITH_CLASS_RE = re.compile(r"<(section|div)\b([^>]*?)class=(['\"])([^'\"]*)(['\"])([^>]*)>", re.IGNORECASE)
_SVG_CLASS_TAG_RE = re.compile(r"<svg\b([^>]*?)class=(['\"])([^'\"]*)(['\"])([^>]*)>", re.IGNORECASE)
_FRONTEND_ROOT_FILES = {
    "index.html",
    "src/app.vue",
    "src/main.ts",
    "src/main.js",
    "apps/web/src/app.vue",
    "apps/web/src/main.ts",
    "apps/web/src/main.js",
    "apps/web/index.html",
}
_GOVERNED_COMPONENT_HINTS = {
    "HeroSection",
    "PricingCard",
    "CTASection",
    "FeatureGrid",
    "ProblemSolutionSection",
}
_BACKEND_ROOT_FILES = {
    "app.py",
    "main.py",
    "apps/api/app/main.py",
}
_DEFAULT_BACKEND_MODULES = {
    "routes": "apps/api/app/routes/lead_capture.py",
    "services": "apps/api/app/services/lead_capture_service.py",
    "repositories": "apps/api/app/repositories/lead_capture_repository.py",
    "schemas": "apps/api/app/schemas/lead_capture.py",
}
_DEFAULT_LANDING_SECTIONS = [
    "HeroSection",
    "ProblemSolutionSection",
    "CapabilitiesGridSection",
    "HowItWorksSection",
    "ROICalculatorSection",
    "ProofSection",
    "PricingSection",
    "CTASection",
    "FooterSection",
]
_PROBABLE_SECRET_LEAK_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |DSA |EC )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"(?im)^\s*(OPENAI_API_KEY|DATABASE_URL|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*['\"]?[^'\"\\s]{8,}"),
    re.compile(r"(?im)^\s*authorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._\\-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]
_NON_EMPTY_CTA_RE = re.compile(r"<PrimaryButton[^>]*>\s*[^<\s][^<]*</PrimaryButton>", re.IGNORECASE)
_EMPTY_CTA_RE = re.compile(r"<PrimaryButton[^>]*>\s*</PrimaryButton>", re.IGNORECASE)
_LANDING_ZONE_COMPONENTS = ("HeroZone", "FeatureZone", "TestimonialsZone", "CTAZone")
_LANDING_ZONE_MARKER_RE = re.compile(r"<!--\s*zone:([a-z0-9_-]+):(start|end)\s*-->", re.IGNORECASE)
_LANDING_ZONE_BLOCK_RE = re.compile(
    r"(<!--\s*zone:(?P<name>[a-z0-9_-]+):start\s*-->)(?P<body>.*?)(<!--\s*zone:(?P=name):end\s*-->)",
    re.IGNORECASE | re.DOTALL,
)
_LANDING_ZONE_INNER_RE = re.compile(r"<(?P<zone>HeroZone|FeatureZone|TestimonialsZone|CTAZone)\b[^>]*>(?P<body>.*?)</(?P=zone)>", re.IGNORECASE | re.DOTALL)


def _contains_probable_secret_leak(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    return any(pattern.search(text) for pattern in _PROBABLE_SECRET_LEAK_PATTERNS)


def _landing_topology_signature(content: str) -> dict[str, object]:
    zone_components = [zone for zone in _LANDING_ZONE_COMPONENTS if f"<{zone}" in content]
    marker_names = sorted({match.group(1).strip().lower() for match in _LANDING_ZONE_MARKER_RE.finditer(content)})
    return {
        "has_page_shell": "<PageShell" in content,
        "zone_components": zone_components,
        "zone_markers": marker_names,
    }


def replace_zone(content: str, zone_name: str, replacement: str) -> str:
    if not isinstance(content, str):
        return content
    target = str(zone_name or "").strip().lower()
    if not target:
        return content

    def _rewrite(match: re.Match[str]) -> str:
        if str(match.group("name") or "").strip().lower() != target:
            return match.group(0)
        start = match.group(1)
        end = match.group(4)
        body = f"\n{replacement.rstrip()}\n"
        return f"{start}{body}{end}"

    return _LANDING_ZONE_BLOCK_RE.sub(_rewrite, content)


def _first_component_markup(content: str, component_name: str) -> str | None:
    if not isinstance(content, str) or not content:
        return None
    token = re.escape(component_name)
    paired = re.search(rf"<{token}\b[^>]*>.*?</{token}>", content, flags=re.IGNORECASE | re.DOTALL)
    if paired:
        return paired.group(0).strip()
    self_closing = re.search(rf"<{token}\b[^>]*/>", content, flags=re.IGNORECASE)
    if self_closing:
        return self_closing.group(0).strip()
    return None


def _added_patch_payload(patch: str) -> str:
    if not isinstance(patch, str) or not patch:
        return ""
    lines: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            lines.append(line[1:])
    return "\n".join(lines)


def _verification_from_action_scope(
    verification: RunPatchVerificationSummary | None,
    touched_files: list[str],
) -> RunPatchVerificationSummary | None:
    if verification is None:
        return None

    normalized_files = [path.strip() for path in touched_files if isinstance(path, str) and path.strip()]
    if verification.status != "NO_SCOPE" or not normalized_files:
        return verification

    requires_confirmation = contains_sensitive_paths(normalized_files) or len(normalized_files) > verification.max_files
    findings = [finding for finding in verification.findings if finding.code != "no_scope"]
    findings.append(
        RunPatchVerificationFinding(
            code="scope_from_actions",
            severity="info",
            title="Patch scope derived from planned actions",
            detail="The planner produced a bounded file list, so execution can continue using the action paths as the verified scope.",
            files=normalized_files[: verification.max_files],
        )
    )
    return verification.model_copy(
        update={
            "status": "REQUIRES_CONFIRMATION" if requires_confirmation else "READY",
            "requires_confirmation": requires_confirmation,
            "file_count": len(normalized_files),
            "verified_files": normalized_files[: verification.max_files],
            "actual_files": normalized_files[: verification.max_files],
            "scope_match": True,
            "findings": findings,
            "suggested_next_action": (
                "Require operator confirmation before patch execution."
                if requires_confirmation
                else "Proceed with the bounded patch and validation sequence."
            ),
        }
    )


def _should_block_for_operator_confirmation(
    verification: RunPatchVerificationSummary | None,
    actions: list[Action],
    *,
    repository_state: str | None = None,
) -> bool:
    if verification is None or not verification.requires_confirmation:
        return False
    if not has_mutating_actions(actions):
        return False
    normalized_state = (repository_state or "").strip().upper()
    findings = list(verification.findings or [])
    finding_codes = {str(finding.code or "").strip().lower() for finding in findings}
    has_high_severity = any((finding.severity or "").lower() == "high" for finding in findings)
    action_paths = {
        str(action.path).strip()
        for action in actions
        if str(getattr(action, "path", "")).strip()
    }
    # Enforce safe happy-path thresholds:
    # - <= 6 bounded files can proceed without manual confirmation.
    # - 7+ files require phased decomposition/review before mutating.
    file_count = max(0, int(verification.file_count or 0))
    if file_count > 6:
        if (
            normalized_state in {"GENESIS", "EARLY_BUILD"}
            and action_paths
            and len(action_paths) <= 2
            and finding_codes.issubset({"missing_tests", "file_cap_exceeded", "scope_from_actions", ""})
        ):
            return False
        return True
    # In GENESIS/EARLY_BUILD, bounded medium-risk scaffolds with only missing-tests warning should continue.
    if (
        normalized_state in {"GENESIS", "EARLY_BUILD"}
        and file_count <= 6
        and (verification.risk_level or "").upper() != "HIGH"
        and not has_high_severity
        and finding_codes.issubset({"missing_tests", "scope_from_actions", ""})
    ):
        return False
    # Unknown/unverified scope should not mutate autonomously.
    if verification.scope_match is False:
        return True
    # Keep hard gate for high-risk scopes or explicitly high-severity findings.
    if (verification.risk_level or "").upper() == "HIGH":
        return True
    return has_high_severity


def _operator_confirmation_next_action(verification: RunPatchVerificationSummary | None) -> str:
    if verification is None:
        return "Confirm the patch plan before allowing mutating actions."
    file_count = max(0, int(verification.file_count or 0))
    if file_count >= 20:
        return "Patch scope is too broad. Create a decomposition plan, then confirm phased execution."
    if file_count >= 7:
        return "Patch scope exceeds autonomous file limit. Split into phased bounded changes, then continue."
    if verification.scope_match is False:
        return "Patch scope is unverified. Rebuild a bounded scope and confirm before mutating."
    return "Confirm the patch plan before allowing mutating actions."


def _target_files_from_payload(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    explicit_values: list[str] = []
    fallback_values: list[str] = []
    scoped = payload.get("target_files")
    if isinstance(scoped, list):
        explicit_values.extend(item for item in scoped if isinstance(item, str))
    elif isinstance(scoped, str) and scoped.strip():
        explicit_values.append(scoped.strip())
    for key in ("target_file", "file", "filepath", "path"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            explicit_values.append(raw.strip())
        elif isinstance(raw, list):
            explicit_values.extend(item for item in raw if isinstance(item, str) and item.strip())
    if isinstance(payload.get("files"), list):
        fallback_values.extend(item for item in payload["files"] if isinstance(item, str))
    if isinstance(payload.get("expected_files"), list):
        fallback_values.extend(item for item in payload["expected_files"] if isinstance(item, str))
    values = explicit_values or fallback_values
    package_affinity = str(payload.get("package_affinity") or "").strip().replace("\\", "/")
    normalized: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            candidate = value.strip().replace("\\", "/")
            if package_affinity.startswith("apps/web"):
                if candidate == "index.html":
                    candidate = "apps/web/index.html"
                elif candidate.startswith("src/"):
                    candidate = f"apps/web/{candidate}"
            normalized.append(candidate)
    return list(dict.fromkeys(normalized))


def _has_operator_confirmation_grant(work_item: WorkItem) -> bool:
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    return bool(payload.get("operator_confirmation_granted") is True)


def _unique_paths(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


def _looks_like_test_path(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return False
    pure = Path(normalized)
    name = pure.name.lower()
    return (
        "tests" in pure.parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _non_test_paths(values: list[str]) -> list[str]:
    return [path for path in _unique_paths(values) if not _looks_like_test_path(path)]


def _project_contract_enforcement_mode(project_contract: dict[str, Any] | None) -> str:
    payload = project_contract if isinstance(project_contract, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    enforcement = payload.get("enforcement") if isinstance(payload.get("enforcement"), dict) else {}
    raw_mode = enforcement.get("mode", summary.get("enforcement_mode"))
    if isinstance(raw_mode, str):
        normalized = raw_mode.strip().lower()
        if normalized in {"off", "warn", "strict"}:
            return normalized
    enabled = bool(enforcement.get("enabled", summary.get("enforcement_enabled", False)))
    return "warn" if enabled else "off"


def _design_context_packet(project_contract: dict[str, Any] | None) -> dict[str, Any]:
    payload = project_contract if isinstance(project_contract, dict) else {}
    design_contract = payload.get("design_contract") if isinstance(payload.get("design_contract"), dict) else {}
    identity = design_contract.get("identity") if isinstance(design_contract.get("identity"), dict) else {}
    typography = design_contract.get("typography") if isinstance(design_contract.get("typography"), dict) else {}
    layout = design_contract.get("layout") if isinstance(design_contract.get("layout"), dict) else {}
    token_registry = design_contract.get("token_registry") if isinstance(design_contract.get("token_registry"), dict) else {}
    allowed_components = design_contract.get("allowed_components") if isinstance(design_contract.get("allowed_components"), list) else []
    if not allowed_components:
        components = design_contract.get("components") if isinstance(design_contract.get("components"), dict) else {}
        registry = components.get("registry")
        if isinstance(registry, list):
            allowed_components = [item for item in registry if isinstance(item, str) and item.strip()]

    visual_tone = str(identity.get("tone") or "").strip()
    layout_density = str(typography.get("density") or "").strip() or str(layout.get("spacing") or "").strip()
    experience_blueprint = str(design_contract.get("experience_blueprint") or "").strip() or "premium_saas"
    return {
        "experience_blueprint": experience_blueprint,
        "visual_tone": visual_tone or "technical_minimal_premium",
        "layout_density": layout_density or "comfortable",
        "allowed_components": allowed_components[:16],
        "token_registry": token_registry if token_registry else {"colors": design_contract.get("tokens", {})},
    }


def _flatten_token_colors(token_registry: dict[str, Any]) -> set[str]:
    colors = token_registry.get("colors") if isinstance(token_registry.get("colors"), dict) else {}
    values: set[str] = set()
    for value in colors.values():
        if isinstance(value, str) and value.strip():
            values.add(value.strip().lower())
    return values


def _coerce_rewrite_aliases(project_contract: dict[str, Any] | None) -> dict[str, str]:
    payload = project_contract if isinstance(project_contract, dict) else {}
    design_contract = payload.get("design_contract") if isinstance(payload.get("design_contract"), dict) else {}
    raw_aliases = design_contract.get("rewrite_aliases") if isinstance(design_contract.get("rewrite_aliases"), dict) else {}
    aliases: dict[str, str] = {}
    for raw_hex, alias in raw_aliases.items():
        if not isinstance(raw_hex, str) or not isinstance(alias, str):
            continue
        normalized_hex = raw_hex.strip().lower()
        normalized_alias = alias.strip()
        if normalized_hex and normalized_alias:
            aliases[normalized_hex] = normalized_alias
    return aliases


def _build_design_token_rewrite_map(
    *,
    project_contract: dict[str, Any] | None,
    allowed_hex: set[str],
) -> dict[str, str]:
    payload = project_contract if isinstance(project_contract, dict) else {}
    design_contract = payload.get("design_contract") if isinstance(payload.get("design_contract"), dict) else {}
    token_registry = design_contract.get("token_registry") if isinstance(design_contract.get("token_registry"), dict) else {}
    colors = token_registry.get("colors") if isinstance(token_registry.get("colors"), dict) else {}
    alias_map = _coerce_rewrite_aliases(project_contract)

    rewrite_map: dict[str, str] = {}
    for raw_hex, alias in alias_map.items():
        alias_value = colors.get(alias)
        if isinstance(alias_value, str) and alias_value.strip():
            normalized = alias_value.strip().lower()
            if normalized in allowed_hex:
                rewrite_map[raw_hex] = normalized
    return rewrite_map


def _normalize_frontend_design_tokens(
    *,
    content: str,
    allowed_hex: set[str],
    rewrite_map: dict[str, str],
) -> tuple[str, list[tuple[str, str]]]:
    replacements: list[tuple[str, str]] = []
    if not isinstance(content, str) or not content:
        return content, replacements

    def _replace(match: re.Match[str]) -> str:
        raw_hex = match.group(0)
        lowered = raw_hex.lower()
        if lowered in allowed_hex:
            return raw_hex
        target = rewrite_map.get(lowered)
        if not target:
            return raw_hex
        replacements.append((raw_hex, target))
        return target

    normalized = _HEX_COLOR_RE.sub(_replace, content)
    return normalized, replacements


def _is_bootstrap_or_genesis_scope(work_item: WorkItem) -> bool:
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    task_source = str(payload.get("task_source") or "").strip().lower()
    repository_state = str(payload.get("repository_state") or "").strip().upper()
    recovery_reason = str(payload.get("recovery_reason") or "").strip().lower()
    return (
        task_source == "genesis"
        or task_source == "genesis_setup"
        or task_source.startswith("genesis.")
        or repository_state in {"GENESIS", "EARLY_BUILD"}
        or recovery_reason == "bootstrap_mode_retry"
    )


def _runtime_governance_mode(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "stability"
    explicit = str(payload.get("runtime_governance_mode") or "").strip().lower()
    if explicit in {"stability", "governed", "emergency"}:
        return explicit
    if bool(getattr(get_settings(), "runtime_emergency_ship_mode_enabled", False)):
        return "emergency"
    repository_state = str(payload.get("repository_state") or "").strip().upper()
    if repository_state in {"GENESIS", "EARLY_BUILD", "ACTIVE_PRODUCT"}:
        return "stability"
    return "stability"


def _stability_warning_violation(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "topology violation",
            "foundation topology violation",
            "primitive composition violation",
            "design contract violation",
            "patch touches files outside the planned scope",
            "layout governance violation",
            "tailwind governance violation",
            "missing max-width/container utility",
            "visual quality gate",
            "polish authority violation",
            "mutation authority violation: operation 'write_file' is not allowed for class polish",
        )
    )


def _emergency_warning_violation(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    hard_block_markers = (
        "unresolved import",
        "could not resolve components",
        "missing runtime file",
        "does not exist",
        "preview cannot boot",
        "preview boot",
        "runtime file",
        "capability governance violation",
        "secret",
        "token",
        "password",
        "webhook",
        "database credential",
        "api key",
        "destructive delete",
        "delete_file",
        "build failure",
        "vite build",
    )
    if any(marker in text for marker in hard_block_markers):
        return False
    return any(
        marker in text
        for marker in (
            "topology violation",
            "foundation topology violation",
            "primitive composition violation",
            "design contract violation",
            "project contract violation",
            "patch touches files outside the planned scope",
            "layout governance violation",
            "tailwind governance violation",
            "missing max-width/container utility",
            "visual quality gate",
            "polish authority violation",
            "mutation authority violation",
            "shell protection violation",
            "zone composition violation",
            "incomplete zone replacement",
            "feature materialization violation",
            "structural contract violation",
            "frontend import normalization violation",
            "frontend import normalization could not resolve components",
        )
    )


_PRIMITIVE_MATURITY_RANK: dict[str, int] = {
    "experimental": 0,
    "stable": 1,
    "verified_visual": 2,
    "production_ready": 3,
}


def _primitive_maturity_registry(payload: dict[str, Any]) -> dict[str, str]:
    registry: dict[str, str] = {}

    raw_registry = payload.get("primitive_registry")
    if isinstance(raw_registry, dict):
        for name, meta in raw_registry.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if isinstance(meta, dict):
                status = str(meta.get("status") or meta.get("maturity") or "").strip().lower()
            else:
                status = str(meta or "").strip().lower()
            if status in _PRIMITIVE_MATURITY_RANK:
                registry[name.strip()] = status

    project_contract = payload.get("project_contract")
    if isinstance(project_contract, dict):
        design_contract = project_contract.get("design_contract")
        if isinstance(design_contract, dict):
            components = design_contract.get("components")
            if isinstance(components, dict):
                maturity = components.get("maturity")
                if isinstance(maturity, dict):
                    for name, status in maturity.items():
                        if not isinstance(name, str) or not name.strip():
                            continue
                        normalized = str(status or "").strip().lower()
                        if normalized in _PRIMITIVE_MATURITY_RANK:
                            registry[name.strip()] = normalized
    return registry


def _primitive_is_verified_visual_or_higher(name: str, maturity_registry: dict[str, str]) -> bool:
    status = maturity_registry.get(name)
    if not status:
        return False
    return _PRIMITIVE_MATURITY_RANK.get(status, -1) >= _PRIMITIVE_MATURITY_RANK["verified_visual"]


def _feature_section_component_candidates(task_text: str) -> list[str]:
    lowered = str(task_text or "").lower()
    section_map = [
        ("hero", "apps/web/src/components/landing/HeroSection.vue"),
        ("testimonial", "apps/web/src/components/landing/TestimonialsSection.vue"),
        ("pricing", "apps/web/src/components/landing/PricingSection.vue"),
        ("cta", "apps/web/src/components/landing/CTASection.vue"),
        ("lead", "apps/web/src/components/landing/LeadCaptureSection.vue"),
    ]
    matches = [path for marker, path in section_map if marker in lowered]
    return matches or ["apps/web/src/components/landing/HeroSection.vue"]


def _should_block_on_human_review_for_work_item(work_item: WorkItem) -> bool:
    if work_item.type in {"PLAN_DAG", "PLAN_BACKEND_TOPOLOGY", "REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
        return False
    if _is_bootstrap_or_genesis_scope(work_item):
        return False
    return True


def _allow_adjacent_scope_expansion(
    *,
    work_item: WorkItem,
    extra_files: list[str],
) -> bool:
    if not extra_files:
        return False
    if work_item.type not in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY", "WRITE_TESTS", "CODE_BACKEND", "GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING"}:
        return False
    if work_item.type not in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"}:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        repository_state = str(payload.get("repository_state") or "").strip().upper()
        if repository_state not in {"GENESIS", "EARLY_BUILD"} and not _is_bootstrap_or_genesis_scope(work_item):
            return False
    normalized = {Path(path).name.strip() for path in extra_files if isinstance(path, str) and path.strip()}
    return bool(normalized) and normalized.issubset(ADJACENT_REPAIR_FILES)


def _fix_test_failure_writable_scope(
    payload: dict[str, Any] | None,
    contract: ExecutionContract | None,
    target_files: list[str],
    allowed_files: list[str],
) -> list[str]:
    preferred: list[str] = []
    if contract is not None and contract.target_files:
        preferred.extend(list(contract.target_files))
    preferred.extend(target_files)
    failing_tests: list[str] = []
    if contract is not None and contract.related_files:
        failing_tests.extend(list(contract.related_files))
    if isinstance(payload, dict):
        if isinstance(payload.get("failing_test_files"), list):
            failing_tests.extend([item for item in payload["failing_test_files"] if isinstance(item, str)])
        if isinstance(payload.get("related_files"), list):
            failing_tests.extend([item for item in payload["related_files"] if isinstance(item, str)])
    scoped_tests = [path for path in _unique_paths(failing_tests) if _looks_like_test_path(path)]
    non_test_preferred = _non_test_paths(preferred)
    if non_test_preferred:
        return _unique_paths(non_test_preferred + scoped_tests)
    non_test_allowed = _non_test_paths(allowed_files)
    if non_test_allowed:
        return _unique_paths(non_test_allowed + scoped_tests)
    return _unique_paths(scoped_tests or preferred or allowed_files)


def _write_tests_writable_scope(
    *,
    target_files: list[str],
    allowed_files: list[str],
) -> list[str]:
    preferred_tests = [path for path in _unique_paths(target_files) if _looks_like_test_path(path)]
    if preferred_tests:
        return preferred_tests
    scoped_tests = [path for path in _unique_paths(allowed_files) if _looks_like_test_path(path)]
    if scoped_tests:
        return scoped_tests
    fallback = _unique_paths(target_files or allowed_files)
    return fallback


def _extract_balanced_json_block(raw: str) -> str | None:
    start = next((idx for idx, ch in enumerate(raw) if ch in "{["), -1)
    if start < 0:
        return None
    opener = raw[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    return None


def _is_backend_codegen_type(work_item_type: str) -> bool:
    return work_item_type in {
        "CODE_BACKEND",
        "GENERATE_ROUTE",
        "GENERATE_SERVICE",
        "GENERATE_REPOSITORY",
        "GENERATE_CAPABILITY_BINDING",
    }


def _extract_structured_json_candidate(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped[0] in "{[":
        return stripped
    fence_match = _JSON_CODE_FENCE_RE.search(raw)
    if fence_match:
        candidate = fence_match.group(1).strip()
        if candidate:
            return candidate
    return _extract_balanced_json_block(raw)


def _payload_text_blob(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key in ("task_title", "goal", "task_description", "title", "description"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    return "\n".join(parts)


def _layout_sensitive_from_payload(payload: dict[str, Any] | None) -> bool:
    text = _payload_text_blob(payload)
    return any(hint in text for hint in LAYOUT_SENSITIVE_HINTS)


def _edit_budget_from_payload(payload: dict[str, Any] | None) -> dict[str, int | str | None]:
    budget = payload.get("edit_budget") if isinstance(payload, dict) else None
    mode = "minimal_patch"
    file_budget = DEFAULT_MAX_PATCH_FILES
    hard_file_budget = HARD_MAX_PATCH_FILES
    if isinstance(budget, dict):
        value = budget.get("mode")
        if isinstance(value, str) and value.strip():
            mode = value.strip()
        value = budget.get("max_files")
        if isinstance(value, int) and value > 0:
            file_budget = value
        value = budget.get("hard_max_files")
        if isinstance(value, int) and value > 0:
            hard_file_budget = value
    hard_file_budget = max(file_budget, hard_file_budget)
    return {
        "mode": mode,
        "file_budget": file_budget,
        "hard_file_budget": hard_file_budget,
    }


def _is_static_frontend_scope(payload: dict[str, Any] | None) -> bool:
    target_files = _target_files_from_payload(payload)
    if not target_files:
        return False
    frontend_suffixes = {".html", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"}
    return all(Path(path).suffix.lower() in frontend_suffixes for path in target_files)


def _sanitize_frontend_scope_paths(paths: list[str]) -> list[str]:
    sanitized: list[str] = []
    for raw in paths:
        if not isinstance(raw, str):
            continue
        path = raw.strip().replace("\\", "/")
        if not path:
            continue
        lowered = path.lower()
        # Keep explicit root allow-list (index.html, src/main.ts, apps/web/src/main.ts, src/app.vue).
        # Reject naked root component filenames (e.g. App.vue, LandingPage.vue) that bypass governed topology.
        if "/" not in path and lowered not in _FRONTEND_ROOT_FILES:
            suffix = Path(path).suffix.lower()
            if suffix in {".vue", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".html"}:
                continue
        sanitized.append(path)
    return list(dict.fromkeys(sanitized))


def _apply_layout_auto_normalization(content: str) -> str:
    updated = content

    def _add_overflow(match: re.Match[str]) -> str:
        tag = match.group(1)
        pre = match.group(2) or ""
        quote = match.group(3)
        classes = match.group(4) or ""
        post = match.group(6) or ""
        tokens = classes.split()
        if not any(token.startswith("overflow-") for token in tokens):
            tokens.append("overflow-hidden")
        return f"<{tag}{pre}class={quote}{' '.join(tokens)}{quote}{post}>"

    updated = _TAG_WITH_CLASS_RE.sub(_add_overflow, updated, count=1)

    def _bound_svg(match: re.Match[str]) -> str:
        pre = match.group(1) or ""
        quote = match.group(2)
        classes = match.group(3) or ""
        post = match.group(5) or ""
        tokens = classes.split()
        if not any(re.fullmatch(r"(w-\d+|size-\d+)", token) for token in tokens):
            tokens.append("w-8")
        if not any(re.fullmatch(r"(h-\d+|size-\d+)", token) for token in tokens):
            tokens.append("h-8")
        return f"<svg{pre}class={quote}{' '.join(tokens)}{quote}{post}>"

    updated = _SVG_CLASS_TAG_RE.sub(_bound_svg, updated)
    return updated


def _is_python_backend_scope(payload: dict[str, Any] | None) -> bool:
    target_files = _target_files_from_payload(payload)
    if not target_files:
        return False
    return all(Path(path).suffix.lower() == ".py" for path in target_files)


def _derive_frontend_topology_plan(
    *,
    work_item: WorkItem,
    payload: dict[str, Any] | None,
    target_files: list[str],
) -> dict[str, Any] | None:
    if work_item.type != "CODE_FRONTEND":
        return None
    if not _is_static_frontend_scope(payload):
        return None
    target_set = {path.strip().lower().replace("\\", "/") for path in target_files if isinstance(path, str) and path.strip()}
    if not (target_set & _FRONTEND_ROOT_FILES):
        return None

    existing = payload.get("frontend_topology_plan") if isinstance(payload, dict) else None
    if isinstance(existing, dict):
        return existing

    section_names: list[str] = []
    title = ""
    if isinstance(payload, dict):
        raw_title = payload.get("task_title") or payload.get("title") or payload.get("task_description")
        if isinstance(raw_title, str):
            title = raw_title.strip()
    normalized_title = title.lower()
    for section in _DEFAULT_LANDING_SECTIONS:
        simplified = section.replace("Section", "").lower()
        if simplified and simplified in normalized_title:
            section_names.append(section)
    if not section_names:
        section_names = list(_DEFAULT_LANDING_SECTIONS)

    component_files = [f"apps/web/src/components/landing/{name}.vue" for name in section_names]
    root_file = next((path for path in target_files if path.strip().lower().replace("\\", "/") in _FRONTEND_ROOT_FILES), "index.html")
    return {
        "planner_stage": "PLAN_FRONTEND_TOPOLOGY_V1",
        "page": "LandingPage",
        "root_file": root_file,
        "sections": section_names,
        "component_files": component_files,
        "composition_file": "apps/web/src/pages/LandingPage.vue",
        "composition_zones": ["HeroZone", "FeatureZone", "TestimonialsZone", "CTAZone"],
        "content_slots": [f"landing.{name.replace('Section', '').lower()}" for name in section_names],
    }


def _derive_backend_topology_plan(
    *,
    work_item: WorkItem,
    payload: dict[str, Any] | None,
    target_files: list[str],
) -> dict[str, Any] | None:
    if work_item.type != "CODE_BACKEND":
        return None
    if not _is_python_backend_scope(payload):
        return None
    target_set = {path.strip().lower().replace("\\", "/") for path in target_files if isinstance(path, str) and path.strip()}
    if not (target_set & _BACKEND_ROOT_FILES):
        return None

    existing = payload.get("backend_topology_plan") if isinstance(payload, dict) else None
    if isinstance(existing, dict):
        return existing

    modules = dict(_DEFAULT_BACKEND_MODULES)
    return {
        "planner_stage": "PLAN_BACKEND_TOPOLOGY_V1",
        "entrypoint_file": next((path for path in target_files if path.strip().lower().replace("\\", "/") in _BACKEND_ROOT_FILES), "app.py"),
        "framework": "fastapi",
        "module_files": modules,
        "rules": {
            "service_layer_required": True,
            "repository_layer_required": True,
            "database_access_forbidden_in_routes": True,
            "max_route_file_lines": 250,
        },
    }


def _stage_scope_violations(
    work_item: WorkItem,
    actions: list[Any],
    touched_files: list[str],
) -> list[str]:
    violations: list[str] = []
    if "PLAN" in work_item.type and has_mutating_actions(actions):
        violations.append("PLAN work items may only return note actions; mutating file operations are out of scope.")
    if work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"} and has_mutating_actions(actions):
        violations.append("REVIEW work items may only return note actions; mutating file operations are out of scope.")
    if work_item.type != "WRITE_TESTS":
        return violations
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    package_affinity = str(payload.get("package_affinity") or "").strip().lower()
    architecture = payload.get("architecture_profile") if isinstance(payload.get("architecture_profile"), dict) else {}
    frontend_stack = str(architecture.get("frontend_stack") or "").strip().lower()
    frontend_mode = package_affinity.startswith("apps/web") or "vue" in frontend_stack or "vite" in frontend_stack
    for path in touched_files:
        name = Path(path).name
        normalized_path = str(path).strip().replace("\\", "/").lower()
        suffix = Path(path).suffix.lower()
        is_python_test = name.startswith("test_") and suffix == ".py"
        is_frontend_test = (
            suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
            and (
                ".spec." in name.lower()
                or ".test." in name.lower()
                or "/tests/" in normalized_path
            )
        )
        if frontend_mode and not is_frontend_test:
            violations.append(
                f"WRITE_TESTS(frontend) may only modify JS/TS test files (*.spec.*|*.test.*) under frontend scope; received out-of-scope file {path}."
            )
        if (not frontend_mode) and not is_python_test:
            violations.append(
                f"WRITE_TESTS may only modify Python test files; received out-of-scope file {path}."
            )
    return violations


class CodexExecutor(TaskExecutor):
    name = "codex"

    def __init__(self, repo_root: Path | None = None):
        self.settings = get_settings()
        self.repo_root = repo_root or Path.cwd()
        self._client: OpenAIClient | None = None
        self._job_manager = AIJobManager()
        # Simple heuristic caps for patch size
        self.max_patch_lines = 2000
        self.max_patch_files = 50
        self.max_patch_ratio_default = 0.4  # per file changed_lines / original_lines
        self.static_frontend_min_lines_single_file = 200
        self.static_frontend_min_lines_multi_file = 120

    def _patch_ratio_for(self, work_item: WorkItem) -> float:
        payload = work_item.payload or {}
        ratio = self.max_patch_ratio_default
        repository_state = str(payload.get("repository_state") or "").strip().upper()
        recovery_strategy = str(payload.get("recovery_strategy") or "").strip().lower()
        if "PLAN" in work_item.type:
            ratio = 0.6
        if "FIX" in work_item.type:
            ratio = 0.25
        if work_item.type == "WRITE_TESTS":
            return float("inf")
        if (
            _is_backend_codegen_type(work_item.type)
            and (
                repository_state in {"GENESIS", "EARLY_BUILD"}
                or recovery_strategy == "write_file_preferred"
            )
        ):
            # Early lifecycle backend scaffolding can legitimately replace most of
            # a tiny bootstrap file; rely on file-count/scope governance instead.
            return float("inf")
        if _is_static_frontend_scope(payload):
            # Static frontend tasks often replace most of a tiny document. Keep the
            # total patch line and file-count guards, but do not block on per-file
            # changed-lines/original-lines ratios for these bounded scopes.
            return float("inf")
        return ratio

    def _frontend_retry_cap_bump_active(self, work_item: WorkItem) -> bool:
        if not bool(getattr(self.settings, "codex_frontend_cap_bump_enabled", True)):
            return False
        if work_item.type != "CODE_FRONTEND":
            return False
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        if not _is_static_frontend_scope(payload):
            return False
        try:
            prior_patch_failures = int(payload.get("prior_patch_failures") or 0)
        except (TypeError, ValueError):
            prior_patch_failures = 0
        recovery_strategy = str(payload.get("recovery_strategy") or "").strip().lower()
        return prior_patch_failures > 0 or recovery_strategy == "write_file_preferred"

    def _strict_output_contract_mode(self, work_item: WorkItem) -> bool:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        if bool(payload.get("strict_output_contract_mode")):
            return True
        try:
            prior_failures = int(payload.get("prior_output_contract_failures") or 0)
        except (TypeError, ValueError):
            prior_failures = 0
        return prior_failures > 0

    def _should_bypass_patch_ratio_limit(self, rel_path: str) -> bool:
        if not bool(getattr(self.settings, "codex_bypass_app_py_patch_ratio_limit", False)):
            return False
        return str(rel_path or "").strip().lower() == "app.py"

    def _should_block_on_human_review_gate(self, work_item: WorkItem) -> bool:
        if bool(getattr(self.settings, "codex_bypass_operator_confirmation_required", False)):
            return False
        return _should_block_on_human_review_for_work_item(work_item)

    def _maybe_bypass_operator_confirmation(
        self,
        decision: MutationGovernanceDecision,
    ) -> MutationGovernanceDecision:
        if not bool(getattr(self.settings, "codex_bypass_operator_confirmation_required", False)):
            return decision
        if not decision.requires_confirmation:
            return decision
        return MutationGovernanceDecision(
            requires_confirmation=False,
            mutation_class=decision.mutation_class,
            reason="operator_confirmation_bypassed_by_flag",
        )

    def _max_patch_lines_for(self, work_item: WorkItem) -> int:
        default_limit = int(self.max_patch_lines)
        if not self._frontend_retry_cap_bump_active(work_item):
            return default_limit
        boosted_limit = int(getattr(self.settings, "codex_frontend_retry_max_patch_lines", default_limit))
        return max(default_limit, boosted_limit)

    def _select_mutation_strategy(
        self,
        *,
        work_item: WorkItem,
        payload: dict[str, Any] | None,
        allowed_files: list[str],
    ) -> tuple[str, list[str], list[str], float, float, str]:
        execution_zone = "layout_zone" if work_item.type == "CODE_FRONTEND" else "logic_zone"
        if execution_zone not in EXECUTION_ZONES:
            execution_zone = "logic_zone"
        if isinstance(payload, dict):
            configured = payload.get("mutation_strategy")
            if isinstance(configured, str):
                normalized = configured.strip().lower()
                if normalized in MUTATION_STRATEGIES:
                    fallback = ["write_file"] if normalized == "apply_patch" else ["apply_patch"]
                    return normalized, fallback, ["configured_in_payload"], 0.1, 0.95, execution_zone
            recovery_strategy = str(payload.get("recovery_strategy") or "").strip().lower()
            if work_item.type == "CODE_FRONTEND" and recovery_strategy == "write_file_preferred":
                return "write_file", ["apply_patch"], ["recovery_strategy_write_file_preferred"], 0.9, 0.9, execution_zone
            if _is_backend_codegen_type(work_item.type) and recovery_strategy == "write_file_preferred":
                return "write_file", ["apply_patch"], ["recovery_strategy_write_file_preferred"], 0.85, 0.9, execution_zone
            repository_state = str(payload.get("repository_state") or "").strip().upper()
            if _is_backend_codegen_type(work_item.type) and repository_state in {"GENESIS", "EARLY_BUILD"}:
                return "write_file", ["apply_patch"], ["repository_state_write_file_preferred"], 0.7, 0.88, execution_zone
        static_frontend_scope = work_item.type == "CODE_FRONTEND" and _is_static_frontend_scope(payload)
        target_files = _target_files_from_payload(payload)
        frontend_candidates = [path for path in dict.fromkeys(target_files + allowed_files) if Path(path).suffix.lower() in {".html", ".css", ".js", ".mjs", ".cjs"}]
        layout_sensitive_hints = _layout_sensitive_from_payload(payload)
        prior_patch_failures = 0
        if isinstance(payload, dict):
            try:
                prior_patch_failures = int(payload.get("prior_patch_failures") or 0)
            except (TypeError, ValueError):
                prior_patch_failures = 0
            recovery_reason = str(payload.get("recovery_reason") or "").strip().lower()
            if "patch" in recovery_reason and "fail" in recovery_reason:
                prior_patch_failures = max(prior_patch_failures, 1)
        retry_count = 1 if prior_patch_failures > 0 else 0
        reasons: list[str] = []
        if static_frontend_scope:
            reasons.append("static_frontend_scope")
        if len(allowed_files) <= 1 and len(target_files) <= 1:
            reasons.append("single_file_scope")
        if any(Path(path).suffix.lower() in {".html", ".css"} for path in (target_files or allowed_files)):
            reasons.append("layout_sensitive_file_type")
        if layout_sensitive_hints:
            reasons.append("layout_sensitive_task_text")
        if prior_patch_failures > 0:
            reasons.append("prior_patch_failures")
        drift_risk_score = 0.15
        if "layout_sensitive_file_type" in reasons:
            drift_risk_score += 0.25
        if "layout_sensitive_task_text" in reasons:
            drift_risk_score += 0.25
        if "bounded_frontend_candidate_scope" in reasons or "single_file_scope" in reasons:
            drift_risk_score += 0.1
        if prior_patch_failures > 0:
            drift_risk_score += 0.35
        drift_risk_score = min(1.0, drift_risk_score)
        if (
            work_item.type == "CODE_FRONTEND"
            and frontend_candidates
            and any(Path(path).suffix.lower() == ".html" for path in frontend_candidates)
            and len(frontend_candidates) <= 3
        ):
            reasons.append("bounded_frontend_candidate_scope")
            strategy_confidence = 0.9 if drift_risk_score >= 0.5 else 0.8
            return "write_file", ["apply_patch"], reasons, drift_risk_score, strategy_confidence, execution_zone
        if work_item.type == "CODE_FRONTEND" and layout_sensitive_hints and frontend_candidates:
            strategy_confidence = 0.88 if drift_risk_score >= 0.5 else 0.8
            return "write_file", ["apply_patch"], reasons, drift_risk_score, strategy_confidence, execution_zone
        if retry_count > 0 and work_item.type == "CODE_FRONTEND":
            return "write_file", ["apply_patch"], reasons, drift_risk_score, 0.92, execution_zone
        if static_frontend_scope and ("single_file_scope" in reasons or "layout_sensitive_file_type" in reasons):
            return "write_file", ["apply_patch"], reasons, drift_risk_score, 0.82, execution_zone
        return "apply_patch", ["write_file"], reasons or ["default_apply_patch"], drift_risk_score, 0.65, execution_zone

    def _system_prompt_for(self, work_item: WorkItem) -> str:
        if work_item.type in {"PLAN_DAG", "PLAN_BACKEND_TOPOLOGY", "REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            return REVIEW_SYSTEM_PROMPT
        return SYSTEM_PROMPT

    def _patch_change_ratio(
        self,
        work_item: WorkItem,
        rel_path: str,
        *,
        additions: int,
        deletions: int,
    ) -> float:
        orig_lines = self._file_line_count(rel_path)
        baseline = max(orig_lines, 1)
        payload = work_item.payload or {}
        if _is_static_frontend_scope(payload):
            target_files = _target_files_from_payload(payload)
            min_lines = (
                self.static_frontend_min_lines_single_file
                if len(target_files) <= 1
                else self.static_frontend_min_lines_multi_file
            )
            new_lines = max(orig_lines + additions - deletions, 0)
            baseline = max(baseline, new_lines, min_lines)
        return (additions + deletions) / baseline

    def _get_client(self) -> OpenAIClient:
        if self._client is None:
            self._client = OpenAIClient()
        return self._client

    def _model_name_for_tier(self, tier: str, *, fallback: str | None = None) -> str:
        return self._job_manager.resolve_model_name(tier) or fallback or self.settings.codex_model

    def _effective_model_tier(
        self,
        *,
        policy,
        work_item: WorkItem,
        attempt: int,
        retry_reason: str | None,
    ) -> str:
        if attempt <= 0:
            return policy.selected_model_tier
        if TIER_ORDER.get(policy.max_model_tier, 0) <= TIER_ORDER.get(policy.selected_model_tier, 0):
            return policy.selected_model_tier
        if retry_reason in {"rate_limit", "timeout", "transient_network_failure"}:
            return policy.selected_model_tier
        if retry_reason in {"structured_parser_failure", "stage_scope_violation", "project_contract_violation"} and work_item.type in {
            "PLAN_DAG",
            "PLAN_BACKEND_TOPOLOGY",
            "WRITE_TESTS",
            "CODE_FRONTEND",
            "REVIEW_DIFF",
            "REVIEW_INTEGRATION",
        }:
            return policy.max_model_tier
        if work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY", "REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"} or policy.risk_level == "high":
            return policy.max_model_tier
        return policy.selected_model_tier

    def _run_budget_exhausted_result(
        self,
        *,
        contract: ExecutionContract | None,
        prepared_job_id: str,
        next_action: str,
    ) -> TaskResult:
        return {
            "status": "FAILED",
            "message": "run_budget_exhausted",
            "payload": {
                "ai_job_id": prepared_job_id,
                "next_action": next_action,
                "failure_class": "budget_exhausted",
                "stop_reason": "run_budget_exhausted",
                "approval_required": True,
                "budget": contract.budget.to_dict() if contract is not None else None,
                "execution_contract": contract.to_dict() if contract is not None else None,
            },
            "warnings": ["run_budget_exhausted"],
        }

    def _budget_next_action(self, work_item: WorkItem) -> str:
        if is_recovery_work_item(work_item):
            return "Increase recovery budget, fork with a higher cap, or manually repair the workspace."
        return "Split the run or reset the run budget before executing more autonomous work."

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        repo_root = Path(context.repo_path) if context.repo_path else self.repo_root
        self.repo_root = repo_root
        contract = context.execution_contract
        repo = RepoTools(
            repo_root,
            logs_path=Path(context.logs_path) if context.logs_path else None,
            execution_contract=contract,
        )
        payload = work_item.payload or {}
        task_id = payload.get("task_id") if isinstance(payload.get("task_id"), str) else None
        if work_item.type in {"PLAN_DAG", "FOUNDATION_VALIDATE", "FRAMEWORK_VALIDATE", "GENESIS_FOUNDATION", "CODE_FRONTEND"}:
            if _runtime_governance_mode(payload if isinstance(payload, dict) else {}) == "emergency":
                ensured = ensure_frontend_foundation_files(repo_root=repo_root)
                if ensured and isinstance(work_item.payload, dict):
                    work_item.payload.setdefault("foundation_bootstrap_repairs", ensured)
                    work_item.payload["foundation_bootstrap_mode"] = "emergency"

        context_bundle = self._build_context(repo, work_item, contract)
        context_bundle.setdefault("meta", {})
        target_files = (
            list(contract.target_files)
            if contract is not None and contract.target_files
            else _target_files_from_payload(work_item.payload)
        )
        allowed_files = (
            list(contract.allowed_files)
            if contract is not None and contract.allowed_files
            else derive_allowed_files(
                work_item_id=str(work_item.id),
                work_item_type=work_item.type,
                payload=work_item.payload,
                plan_snapshot=context.plan_snapshot,
            )
        )
        if work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"}:
            writable_scope = _fix_test_failure_writable_scope(work_item.payload, contract, target_files, allowed_files)
            if writable_scope:
                target_files = writable_scope
                allowed_files = list(writable_scope)
                if contract is not None:
                    # Keep patch guard scope aligned with recovery writable scope.
                    contract.target_files = list(writable_scope)
                    contract.allowed_files = list(writable_scope)
        elif work_item.type == "WRITE_TESTS":
            writable_scope = _write_tests_writable_scope(target_files=target_files, allowed_files=allowed_files)
            if writable_scope:
                target_files = writable_scope
                allowed_files = list(writable_scope)
        elif target_files:
            allowed_files = list(dict.fromkeys(target_files + allowed_files))
        if work_item.type in {"CODE_FRONTEND", "GENESIS_FOUNDATION"}:
            target_files = _sanitize_frontend_scope_paths(target_files)
            allowed_files = _sanitize_frontend_scope_paths(allowed_files)
            payload_dict = work_item.payload if isinstance(work_item.payload, dict) else {}
            mutation_class = str(payload_dict.get("mutation_class") or "").strip().upper()
            task_text = " ".join(
                str(payload_dict.get(key) or "").strip()
                for key in ("task_title", "title", "goal", "task_description")
            )
            if work_item.type == "CODE_FRONTEND" and mutation_class == "FEATURE":
                feature_scope = ["apps/web/src/pages/LandingPage.vue", *_feature_section_component_candidates(task_text)]
                target_files = list(dict.fromkeys([*feature_scope, *target_files]))
                allowed_files = list(dict.fromkeys([*feature_scope, *allowed_files]))
            if _runtime_governance_mode(work_item.payload if isinstance(work_item.payload, dict) else {}) == "emergency":
                allowed_files = list(
                    dict.fromkeys(
                        [
                            *allowed_files,
                            "apps/web/src/components",
                            "apps/web/src/layouts",
                            "apps/web/src/pages",
                            "apps/web/src/styles",
                            "runtime-contracts/component-manifest.json",
                            "runtime-contracts/foundation_version.json",
                            "runtime-contracts/topology_hash.json",
                        ]
                    )
                )
                target_files = list(dict.fromkeys([*target_files, *allowed_files]))
                ensured = ensure_frontend_foundation_files(repo_root=repo_root)
                if ensured and isinstance(work_item.payload, dict):
                    work_item.payload["foundation_bootstrap_repairs"] = ensured
                    work_item.payload["foundation_bootstrap_mode"] = "emergency"
        session = getattr(context, "session", None)
        if session is not None:
            try:
                payload_dict = work_item.payload if isinstance(work_item.payload, dict) else {}
                topology = (
                    payload_dict.get("backend_topology_plan")
                    if isinstance(payload_dict.get("backend_topology_plan"), dict)
                    else {}
                )
                graph_caps = [
                    str(item).strip().lower()
                    for item in (
                        list(work_item.required_capabilities or [])
                        + list(topology.get("allowed_capabilities") or [])
                    )
                    if str(item).strip()
                ]
                anchor_scope = list(dict.fromkeys([*target_files, *allowed_files]))[:12]
                if anchor_scope:
                    safe_scope = await get_safe_mutation_scope(
                        session,
                        tenant_id=work_item.tenant_id,
                        project_id=work_item.project_id,
                        anchor_files=anchor_scope,
                        capabilities=graph_caps,
                        depth=1,
                        limit=50,
                    )
                    safe_paths = [node.path for node in safe_scope.files if isinstance(node.path, str) and node.path.strip()]
                    if safe_paths:
                        allowed_files = list(dict.fromkeys([*anchor_scope, *safe_paths]))
                        context_bundle["meta"]["repo_intelligence_scope"] = {
                            "anchor_files": anchor_scope,
                            "capabilities": graph_caps,
                            "safe_scope_files": safe_paths[:40],
                        }
            except Exception:
                # Best effort only; executor should still run with existing scope derivation.
                pass

        topology_plan = _derive_frontend_topology_plan(
            work_item=work_item,
            payload=work_item.payload if isinstance(work_item.payload, dict) else {},
            target_files=target_files,
        )
        if isinstance(topology_plan, dict):
            if isinstance(work_item.payload, dict):
                work_item.payload["frontend_topology_plan"] = topology_plan
            planned_component_files = [
                path for path in topology_plan.get("component_files", [])
                if isinstance(path, str) and path.strip()
            ]
            if planned_component_files:
                allowed_files = list(dict.fromkeys(allowed_files + planned_component_files))
        backend_topology_plan = _derive_backend_topology_plan(
            work_item=work_item,
            payload=work_item.payload if isinstance(work_item.payload, dict) else {},
            target_files=target_files,
        )
        if isinstance(backend_topology_plan, dict):
            if isinstance(work_item.payload, dict):
                work_item.payload["backend_topology_plan"] = backend_topology_plan
            module_files = backend_topology_plan.get("module_files")
            if isinstance(module_files, dict):
                planned_backend_files = [
                    path for path in module_files.values()
                    if isinstance(path, str) and path.strip()
                ]
                if planned_backend_files:
                    allowed_files = list(dict.fromkeys(allowed_files + planned_backend_files))
        (
            selected_mutation_strategy,
            mutation_strategy_fallbacks,
            mutation_strategy_reasons,
            drift_risk_score,
            strategy_confidence,
            execution_zone,
        ) = self._select_mutation_strategy(
            work_item=work_item,
            payload=work_item.payload if isinstance(work_item.payload, dict) else {},
            allowed_files=allowed_files,
        )
        if isinstance(work_item.payload, dict):
            work_item.payload["mutation_strategy"] = selected_mutation_strategy
            work_item.payload["mutation_strategy_fallbacks"] = mutation_strategy_fallbacks
            work_item.payload["drift_risk_score"] = drift_risk_score
            work_item.payload["strategy_confidence"] = strategy_confidence
            work_item.payload["execution_zone"] = execution_zone
        effective_mutation_strategy = selected_mutation_strategy
        mutation_strategy_transitions: list[dict[str, str]] = []
        edit_budget = (
            {
                "mode": contract.scope_mode,
                "file_budget": contract.file_budget,
                "hard_file_budget": contract.hard_file_budget,
            }
            if contract is not None
            else _edit_budget_from_payload(work_item.payload)
        )
        context_bundle["meta"]["workspace"] = {
            "workspace_root": context.workspace_root,
            "repo_path": context.repo_path,
            "artifacts_path": context.artifacts_path,
            "logs_path": context.logs_path,
            "patches_path": context.patches_path,
            "branch_name": context.branch_name,
            "workspace_status": context.workspace_status,
            "simulation_mode": context.simulation_mode,
            "command_audit_path": context.command_audit_path,
            "cleanup_policy": context.cleanup_policy,
        }
        if isinstance(context.architecture_profile, dict):
            context_bundle["meta"]["architecture_profile"] = context.architecture_profile
        if isinstance(context.project_contract, dict):
            context_bundle["meta"]["project_contract"] = context.project_contract
            context_bundle["meta"]["design_context_packet"] = _design_context_packet(context.project_contract)
        if isinstance(topology_plan, dict):
            context_bundle["meta"]["frontend_topology_plan"] = topology_plan
        if isinstance(backend_topology_plan, dict):
            context_bundle["meta"]["backend_topology_plan"] = backend_topology_plan
        if contract is not None:
            context_bundle["meta"]["execution_contract"] = contract.to_dict()
        if isinstance(context.plan_snapshot, dict):
            context_bundle["meta"]["run_plan"] = {
                "goal": context.plan_snapshot.get("goal"),
                "rationale": context.plan_snapshot.get("rationale"),
                "validation_steps": context.plan_snapshot.get("validation_steps", []),
                "expected_files": context.plan_snapshot.get("expected_files", []),
                "steps": [
                    {
                        "title": step.get("title"),
                        "phase": step.get("phase"),
                        "success_criteria": step.get("success_criteria", []),
                    }
                    for step in context.plan_snapshot.get("steps", [])[:8]
                    if isinstance(step, dict)
                ],
            }
        context_bundle["meta"]["patch_guard"] = build_patch_guard_meta(
            context,
            allowed_files,
            file_budget=int(edit_budget["file_budget"]),
            hard_file_budget=int(edit_budget["hard_file_budget"]),
            scope_mode=str(edit_budget["mode"]) if edit_budget.get("mode") else None,
            target_files=target_files,
        )
        context_bundle["meta"]["mutation_strategy"] = {
            "selected": selected_mutation_strategy,
            "fallback_chain": mutation_strategy_fallbacks,
            "reasons": mutation_strategy_reasons,
            "drift_risk_score": drift_risk_score,
            "strategy_confidence": strategy_confidence,
            "execution_zone": execution_zone,
        }
        recovery_mode = is_recovery_work_item(work_item)
        if contract is not None:
            contract.budget.refresh(recovery_mode=recovery_mode)
            context_bundle["meta"]["execution_contract"] = contract.to_dict()
        if contract is not None and contract.budget.budget_mode == "BLOCKED":
            next_action = (
                "Increase recovery budget, fork with a higher cap, or manually repair the workspace."
                if recovery_mode
                else self._budget_next_action(work_item)
            )
            return {
                "status": "FAILED",
                "message": "run_budget_exhausted",
                "payload": {
                    "next_action": next_action,
                    "budget": contract.budget.to_dict(),
                    "validation_state": contract.validation_state,
                    "retry_state": contract.retry_state,
                    "recovery_blocked": recovery_mode,
                },
                "warnings": ["run_budget_exhausted"],
            }

        graph_context = await self._load_graph_context(work_item)
        if graph_context:
            context_bundle["graph_context"] = graph_context
        job_request = self._build_ai_job_request(work_item, context_bundle, allowed_files, contract)
        context_pack = await self._job_manager.load_context_pack(job_request)
        if context_pack.fragments:
            context_bundle["meta"]["cached_context"] = context_pack.fragments
        context_bundle["meta"]["context_pack"] = {
            "key": context_pack.pack_key,
            "hash": context_pack.pack_hash,
            "pack_cache_hit": context_pack.pack_cache_hit,
        }

        # Adaptive patch ratio based on stage
        ratio = self._patch_ratio_for(work_item)

        # Build minimal context (future: fetch relevant files)
        user_prompt = json.dumps(
            {
                "work_item": {
                    "id": str(work_item.id),
                    "type": work_item.type,
                    "key": work_item.key,
                    "payload": work_item.payload or {},
                    "required_capabilities": work_item.required_capabilities or [],
                },
                "instructions": self._instructions_for(work_item, context),
                "context_files": context_bundle.get("files", {}),
                "meta": context_bundle.get("meta", {}),
                "artifacts": context_bundle.get("artifacts", {}),
                "graph_context": context_bundle.get("graph_context"),
                "output_schema": CodexPlan.model_json_schema(),
            }
        )
        system_prompt = self._system_prompt_for(work_item)
        filters_used = ["diff_narrowing", "stack_trace_extraction", "path_hint_lookup", "graph_context_lookup"]
        if context_pack.fragments:
            filters_used.append("context_pack_lookup")
        initial_policy = self._job_manager.route_job(job_request)
        completion_token_estimate = min(
            self.settings.codex_max_tokens,
            contract.budget.completion_token_cap
            if contract is not None and contract.budget.completion_token_cap is not None
            else self.settings.codex_max_tokens,
        )
        completion_token_estimate = self._initial_completion_token_estimate(
            base_max_tokens=completion_token_estimate,
            selected_model_tier=initial_policy.selected_model_tier,
            work_item=work_item,
            contract=contract,
        )
        # Planning/review stages and bootstrap/genesis scopes should not hard-stop
        # on human-review gating; bootstrap flows must converge end-to-end.
        should_block_on_human_review = self._should_block_on_human_review_gate(work_item)
        prepared = await self._job_manager.prepare_job(
            job_request,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            filters_used=filters_used,
            cache_hit_count=context_pack.cache_hits,
            context_pack=context_pack,
            completion_token_estimate=completion_token_estimate,
            block_on_human_review=should_block_on_human_review,
        )
        if prepared.stop_reason:
            log.warning(
                "AI execution blocked run_id=%s work_item_id=%s task_id=%s ai_job_id=%s work_item_type=%s tier=%s model=%s provider=%s stop_reason=%s next_action=%s",
                work_item.run_id,
                work_item.id,
                task_id,
                prepared.job_id,
                work_item.type,
                prepared.policy.selected_model_tier,
                prepared.model_name,
                self.settings.llm_provider,
                prepared.stop_reason,
                prepared.next_action,
            )
            return {
                "status": "FAILED",
                "message": prepared.stop_reason,
                "payload": {
                    "ai_job_id": str(prepared.job_id),
                    "failure_class": prepared.stop_reason,
                    "stop_reason": prepared.stop_reason,
                    "approval_required": prepared.stop_reason in {"budget_exceeded", "run_budget_exhausted"},
                    "next_action": prepared.next_action,
                    "estimated_cost_cents": prepared.estimated_cost_cents,
                    "context_size": prepared.context_size,
                    "run_id": str(work_item.run_id),
                    "work_item_id": str(work_item.id),
                    "task_id": task_id,
                    "provider": self.settings.llm_provider,
                    "model_name": prepared.model_name,
                    "selected_model_tier": prepared.policy.selected_model_tier,
                    "policy": self._policy_payload(prepared.policy),
                },
                "warnings": ["ai_policy_stop"],
            }

        plan: CodexPlan | None = None
        raw = ""
        usage: dict[str, Any] = {}
        current_user_prompt = user_prompt
        parse_retry_count = 0
        current_completion_token_estimate = completion_token_estimate
        usage_input_tokens = 0
        usage_output_tokens = 0
        usage_cost_cents = 0.0
        attempt_tiers: list[str] = []
        retry_reason: str | None = None
        effective_model_tier = prepared.policy.selected_model_tier
        effective_model_name = prepared.model_name or self.settings.codex_model
        model_retry_count = 0
        client = self._get_client()
        log.info(
            "AI execution starting run_id=%s work_item_id=%s task_id=%s ai_job_id=%s work_item_type=%s tier=%s model=%s provider=%s client_method=%s openai_sdk_version=%s policy=%s",
            work_item.run_id,
            work_item.id,
            task_id,
            prepared.job_id,
            work_item.type,
            prepared.policy.selected_model_tier,
            prepared.model_name,
            self.settings.llm_provider,
            client.method_name(),
            client.sdk_version(),
            self._policy_payload(prepared.policy),
        )
        max_attempts = prepared.policy.max_retries + STRUCTURED_OUTPUT_RETRY_LIMIT + 1
        for attempt in range(max_attempts):
            current_model_tier = self._effective_model_tier(
                policy=prepared.policy,
                work_item=work_item,
                attempt=attempt,
                retry_reason=retry_reason,
            )
            current_model_name = self._model_name_for_tier(
                current_model_tier,
                fallback=prepared.model_name or self.settings.codex_model,
            )
            await self._job_manager.record_attempt(prepared.job_id)
            try:
                attempt_temperature = 0.0 if self._strict_output_contract_mode(work_item) else self.settings.codex_temperature
                raw, usage = await client.generate(
                    system_prompt,
                    current_user_prompt,
                    model=current_model_name,
                    temperature=attempt_temperature,
                    max_tokens=current_completion_token_estimate,
                    timeout=self.settings.codex_timeout_seconds,
                )
                current_input_tokens = int(usage.get("input_tokens") or estimate_tokens(system_prompt + current_user_prompt))
                current_output_tokens = int(usage.get("output_tokens") or estimate_tokens(raw))
                usage_input_tokens += current_input_tokens
                usage_output_tokens += current_output_tokens
                usage_cost_cents = round(
                    usage_cost_cents
                    + self._job_manager.estimate_cost_cents(
                        current_model_tier,
                        current_input_tokens,
                        current_output_tokens,
                    ),
                    4,
                )
                usage = {
                    "input_tokens": usage_input_tokens,
                    "output_tokens": usage_output_tokens,
                }
                attempt_tiers.append(current_model_tier)
                effective_model_tier = current_model_tier
                effective_model_name = current_model_name
                contract = await self._record_execution_budget(
                    context,
                    prepared_job_id=str(prepared.job_id),
                    work_item_id=str(work_item.id),
                    selected_model_tier=current_model_tier,
                    input_tokens=current_input_tokens,
                    output_tokens=current_output_tokens,
                )
                if contract is not None and contract.budget.budget_mode == "BLOCKED":
                    next_action = self._budget_next_action(work_item)
                    await self._job_manager.fail_job(
                        prepared.job_id,
                        reason="run_budget_exhausted",
                        next_action=next_action,
                        error_kind="run_budget_exhausted",
                        input_tokens=usage_input_tokens,
                        output_tokens=usage_output_tokens,
                        actual_cost_cents=usage_cost_cents,
                        details={
                            "attempt_tiers": attempt_tiers,
                            "provider": self.settings.llm_provider,
                            "model_name": current_model_name,
                            "budget": contract.budget.to_dict(),
                        },
                    )
                    return self._run_budget_exhausted_result(
                        contract=contract,
                        prepared_job_id=str(prepared.job_id),
                        next_action=next_action,
                    )
                plan = self._parse_codex_plan(raw)
                break
            except Exception as exc:
                parse_failure = isinstance(exc, json.JSONDecodeError) or "validation" in exc.__class__.__name__.lower()
                retry_reason = "structured_parser_failure" if parse_failure else retry_error_kind(exc)
                if parse_failure and parse_retry_count < STRUCTURED_OUTPUT_RETRY_LIMIT:
                    parse_retry_count += 1
                    await self._job_manager.record_retry(prepared.job_id, "structured_parser_failure")
                    next_retry_tier = self._effective_model_tier(
                        policy=prepared.policy,
                        work_item=work_item,
                        attempt=attempt + 1,
                        retry_reason=retry_reason,
                    )
                    current_completion_token_estimate = self._parse_retry_max_tokens(
                        current_max_tokens=current_completion_token_estimate,
                        selected_model_tier=next_retry_tier,
                        work_item=work_item,
                        contract=contract,
                    )
                    current_user_prompt = self._build_parse_retry_prompt(
                        user_prompt=user_prompt,
                        raw=raw,
                        error=exc,
                        work_item=work_item,
                        allowed_files=allowed_files,
                        retry_count=parse_retry_count,
                    )
                    continue
                error_kind = retry_reason
                if not parse_failure and model_retry_count < prepared.policy.max_retries and is_retryable_error(exc):
                    await self._job_manager.record_retry(prepared.job_id, error_kind)
                    await asyncio.sleep(min(2 ** model_retry_count, 3))
                    model_retry_count += 1
                    continue
                failure_reason = "output_contract_invalid" if parse_failure else "model_call_failed"
                await self._job_manager.fail_job(
                    prepared.job_id,
                    reason=failure_reason,
                    next_action="Reduce scope, tighten context, or request human review before retrying.",
                    error_kind=error_kind,
                    input_tokens=usage_input_tokens,
                    output_tokens=usage_output_tokens,
                    actual_cost_cents=usage_cost_cents,
                    details={
                        "error_message": str(exc),
                        "exception_type": exc.__class__.__name__,
                        "provider": self.settings.llm_provider,
                        "model_name": current_model_name,
                        "client_method": client.method_name(),
                        "openai_sdk_version": client.sdk_version(),
                        "selected_model_tier": current_model_tier,
                        "attempt_tiers": attempt_tiers,
                        "policy": self._policy_payload(prepared.policy),
                        "run_id": str(work_item.run_id),
                        "work_item_id": str(work_item.id),
                        "task_id": task_id,
                        "work_item_type": work_item.type,
                    },
                )
                log.exception(
                    "AI execution failed run_id=%s work_item_id=%s task_id=%s ai_job_id=%s work_item_type=%s tier=%s model=%s provider=%s client_method=%s openai_sdk_version=%s failure_reason=%s error_kind=%s",
                    work_item.run_id,
                    work_item.id,
                    task_id,
                    prepared.job_id,
                    work_item.type,
                    current_model_tier,
                    current_model_name,
                    self.settings.llm_provider,
                    client.method_name(),
                    client.sdk_version(),
                    failure_reason,
                    error_kind,
                    exc_info=exc,
                )
                return {
                    "status": "FAILED",
                    "message": f"AI policy halted execution: {failure_reason}",
                    "payload": {
                        "raw": raw,
                        "ai_job_id": str(prepared.job_id),
                        "next_action": "Reduce scope, tighten context, or request human review before retrying.",
                        "error_message": str(exc),
                        "exception_type": exc.__class__.__name__,
                        "error_kind": error_kind,
                        "run_id": str(work_item.run_id),
                        "work_item_id": str(work_item.id),
                        "task_id": task_id,
                        "work_item_type": work_item.type,
                        "provider": self.settings.llm_provider,
                        "model_name": current_model_name,
                        "client_method": client.method_name(),
                        "openai_sdk_version": client.sdk_version(),
                        "selected_model_tier": current_model_tier,
                        "attempt_tiers": attempt_tiers,
                        "policy": self._policy_payload(prepared.policy),
                    },
                    "warnings": ["ai_policy_stop"],
                }

        if plan is None:
            return {
                "status": "FAILED",
                "message": "ai_plan_missing",
                "payload": {"ai_job_id": str(prepared.job_id)},
                "warnings": ["ai_policy_stop"],
            }
        if plan.confidence is not None and plan.confidence < self.settings.ai_low_confidence_threshold:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="low_confidence_output",
                next_action="Narrow the file set or request human review before applying the patch.",
                error_kind="low_confidence_reasoning",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                actual_cost_cents=usage_cost_cents,
                approval_state="pending",
                status="blocked",
                details={"confidence": plan.confidence, "attempt_tiers": attempt_tiers, "model_name": effective_model_name},
            )
            return {
                "status": "FAILED",
                "message": "low_confidence_output",
                "payload": {
                    "confidence": plan.confidence,
                    "ai_job_id": str(prepared.job_id),
                    "next_action": "Narrow the file set or request human review before applying the patch.",
                },
                "warnings": ["requires_confirmation"],
            }

        patch_guard = None
        patch_repair_attempted = False
        patch_repair_parse_retry_attempted = False
        stage_scope_repair_attempted = False
        project_contract_repair_attempted = False
        content_binding_records: list[dict[str, Any]] = []
        content_binding_telemetry: dict[str, Any] = {
            "content_binding_attempted": False,
            "content_binding_enabled": False,
            "content_binding_fallback_used": False,
        }
        frontend_composition_telemetry: dict[str, float] = {
            "layout_integrity_score": 1.0,
            "responsive_safety_score": 1.0,
            "overflow_risk_score": 0.0,
            "typography_consistency_score": 1.0,
            "visual_composition_score": 1.0,
        }
        foundation_quality_telemetry: dict[str, float] = {
            "foundation_layout_score": 1.0,
            "navigation_integrity": 1.0,
            "responsive_shell_score": 1.0,
            "design_system_score": 1.0,
        }
        import_resolution_telemetry: dict[str, Any] = {
            "import_resolution_attempts": 0,
            "resolved_component_imports": [],
            "unresolved_component_imports": [],
            "import_normalization_repairs": 0,
        }
        while True:
            plan.actions, zone_composer_violations = self._enforce_feature_zone_composer(
                work_item=work_item,
                repo_root=repo_root,
                actions=plan.actions,
            )
            content_binding_violations, content_binding_records, content_binding_telemetry = self._content_binding_pass(
                work_item=work_item,
                actions=plan.actions,
            )
            payload_for_recovery = work_item.payload if isinstance(work_item.payload, dict) else {}
            recovery_strategy = str(payload_for_recovery.get("recovery_strategy") or "").strip().lower()
            auto_normalize_layout = bool(payload_for_recovery.get("layout_auto_normalize")) or recovery_strategy in {
                "layout_composition_repair",
                "write_file_preferred",
            }
            if work_item.type == "CODE_FRONTEND" and auto_normalize_layout:
                for action in plan.actions:
                    if getattr(action, "type", None) != "write_file":
                        continue
                    path = str(getattr(action, "path", "") or "").strip().replace("\\", "/").lower()
                    content = getattr(action, "content", None)
                    if not isinstance(content, str) or not path.endswith(".vue"):
                        continue
                    if "/components/" in path or path.endswith("/pages/landingpage.vue"):
                        action.content = _apply_layout_auto_normalization(content)
            plan.actions, landing_zone_warnings, landing_zone_violations = self._auto_normalize_landing_zone_actions(
                work_item=work_item,
                actions=plan.actions,
            )
            plan.actions, import_resolution_telemetry, import_resolution_violations = self._normalize_frontend_import_actions(
                work_item=work_item,
                repo_root=repo_root,
                actions=plan.actions,
            )
            design_violation_records = self._design_validation_records(
                work_item=work_item,
                actions=plan.actions,
                project_contract=context.project_contract if isinstance(context.project_contract, dict) else None,
            )
            design_violations = [record["message"] for record in design_violation_records]
            project_contract_check = evaluate_project_contract_precheck(
                actions=plan.actions,
                project_contract=context.project_contract if isinstance(context.project_contract, dict) else None,
            )
            merged_project_violations = [*project_contract_check.violations, *design_violations]
            if (
                merged_project_violations
                and not project_contract_repair_attempted
                and self._is_project_contract_repair_candidate(
                    work_item=work_item,
                    violations=merged_project_violations,
                )
            ):
                project_contract_repair_attempted = True
                await self._job_manager.record_retry(prepared.job_id, "project_contract_violation")
                try:
                    plan, raw, repair_usage, repair_model_tier, repair_model_name = (
                        await self._repair_plan_after_project_contract_violation(
                            client=client,
                            prepared=prepared,
                            user_prompt=user_prompt,
                            allowed_files=allowed_files,
                            violations=merged_project_violations,
                            work_item=work_item,
                            contract=contract,
                            enforcement_mode=project_contract_check.mode,
                        )
                    )
                except Exception as repair_exc:
                    plan.warnings.append(f"project_contract_repair_failed:{repair_exc}")
                else:
                    repair_input_tokens = int(
                        repair_usage.get("input_tokens") or estimate_tokens(system_prompt + user_prompt)
                    )
                    repair_output_tokens = int(repair_usage.get("output_tokens") or estimate_tokens(raw))
                    usage_input_tokens += repair_input_tokens
                    usage_output_tokens += repair_output_tokens
                    usage_cost_cents = round(
                        usage_cost_cents
                        + self._job_manager.estimate_cost_cents(
                            repair_model_tier,
                            repair_input_tokens,
                            repair_output_tokens,
                        ),
                        4,
                    )
                    usage = {
                        "input_tokens": usage_input_tokens,
                        "output_tokens": usage_output_tokens,
                    }
                    attempt_tiers.append(repair_model_tier)
                    effective_model_tier = repair_model_tier
                    effective_model_name = repair_model_name
                    contract = await self._record_execution_budget(
                        context,
                        prepared_job_id=str(prepared.job_id),
                        work_item_id=str(work_item.id),
                        selected_model_tier=repair_model_tier,
                        input_tokens=repair_input_tokens,
                        output_tokens=repair_output_tokens,
                    )
                    if contract is not None and contract.budget.budget_mode == "BLOCKED":
                        next_action = self._budget_next_action(work_item)
                        await self._job_manager.fail_job(
                            prepared.job_id,
                            reason="run_budget_exhausted",
                            next_action=next_action,
                            error_kind="run_budget_exhausted",
                            input_tokens=usage_input_tokens,
                            output_tokens=usage_output_tokens,
                            actual_cost_cents=usage_cost_cents,
                            details={
                                "attempt_tiers": attempt_tiers,
                                "provider": self.settings.llm_provider,
                                "model_name": repair_model_name,
                                "budget": contract.budget.to_dict(),
                            },
                        )
                        return self._run_budget_exhausted_result(
                            contract=contract,
                            prepared_job_id=str(prepared.job_id),
                            next_action=next_action,
                        )
                    continue

            patch_guard = evaluate_patch_guard(
                actions=plan.actions,
                allowed_files=allowed_files,
                file_budget=int(edit_budget["file_budget"]),
                hard_file_budget=int(edit_budget["hard_file_budget"]),
                contract=contract,
                project_contract=context.project_contract if isinstance(context.project_contract, dict) else None,
                work_item_type=work_item.type,
                work_item_payload=work_item.payload if isinstance(work_item.payload, dict) else None,
            )
            extra_scope_files = [path for path in patch_guard.touched_files if path not in patch_guard.allowed_files]
            if _allow_adjacent_scope_expansion(work_item=work_item, extra_files=extra_scope_files):
                expanded_scope = list(dict.fromkeys(patch_guard.allowed_files + extra_scope_files))
                allowed_files = expanded_scope
                if contract is not None:
                    contract.allowed_files = list(expanded_scope)
                patch_guard = evaluate_patch_guard(
                    actions=plan.actions,
                    allowed_files=expanded_scope,
                    file_budget=int(edit_budget["file_budget"]),
                    hard_file_budget=int(edit_budget["hard_file_budget"]),
                    contract=contract,
                    project_contract=context.project_contract if isinstance(context.project_contract, dict) else None,
                    work_item_type=work_item.type,
                    work_item_payload=work_item.payload if isinstance(work_item.payload, dict) else None,
                )
                async with SessionLocal() as session:
                    await record_event(
                        session,
                        project_id=work_item.project_id,
                        run_id=work_item.run_id,
                        work_item_id=work_item.id,
                        event_type="RUN_SCOPE_EXPANDED",
                        actor_type="SYSTEM",
                        tenant_id=work_item.tenant_id,
                        payload={
                            "work_item_id": str(work_item.id),
                            "reason": "adjacent_repair_scope_expansion",
                            "repository_state": str((work_item.payload or {}).get("repository_state") or ""),
                            "added_files": extra_scope_files,
                            "allowed_files_count": len(expanded_scope),
                        },
                    )
            stage_violations = _stage_scope_violations(work_item, plan.actions, patch_guard.touched_files)
            stage_violations.extend(zone_composer_violations)
            stage_violations.extend(content_binding_violations)
            stage_violations.extend(landing_zone_violations)
            stage_violations.extend(import_resolution_violations)
            if landing_zone_warnings:
                patch_guard.project_warnings.extend(landing_zone_warnings)
            stage_violations.extend(
                self._frontend_writefile_violations(
                    work_item=work_item,
                    actions=plan.actions,
                )
            )
            stage_violations.extend(
                self._backend_writefile_violations(
                    work_item=work_item,
                    actions=plan.actions,
                )
            )
            if work_item.type == "CODE_FRONTEND":
                stage_violations.extend(
                    validate_frontend_topology(actions=plan.actions, enforce=True)
                )
                composition_assessment = evaluate_frontend_composition_governance(
                    actions=plan.actions,
                    enforce=True,
                    repo_root=repo_root,
                )
                frontend_composition_telemetry = {
                    "layout_integrity_score": composition_assessment.layout_integrity_score,
                    "responsive_safety_score": composition_assessment.responsive_safety_score,
                    "overflow_risk_score": composition_assessment.overflow_risk_score,
                    "typography_consistency_score": composition_assessment.typography_consistency_score,
                    "visual_composition_score": composition_assessment.visual_composition_score,
                }
                stage_violations.extend(composition_assessment.violations)
            if work_item.type == "GENESIS_FOUNDATION":
                foundation_assessment = evaluate_frontend_foundation_governance(actions=plan.actions, enforce=True)
                foundation_quality_telemetry = {
                    "foundation_layout_score": foundation_assessment.foundation_layout_score,
                    "navigation_integrity": foundation_assessment.navigation_integrity,
                    "responsive_shell_score": foundation_assessment.responsive_shell_score,
                    "design_system_score": foundation_assessment.design_system_score,
                }
                stage_violations.extend(foundation_assessment.violations)
            stage_violations.extend(
                self._mutation_strategy_violations(
                    work_item=work_item,
                    selected_strategy=effective_mutation_strategy,
                    actions=plan.actions,
                )
            )
            stage_violations.extend(design_violations)
            payload_dict_for_mode = work_item.payload if isinstance(work_item.payload, dict) else {}
            runtime_governance_mode = _runtime_governance_mode(payload_dict_for_mode)
            if stage_violations:
                if runtime_governance_mode == "stability":
                    downgraded = [item for item in stage_violations if _stability_warning_violation(item)]
                    blocking = [item for item in stage_violations if item not in downgraded]
                    if downgraded:
                        patch_guard.project_warnings.extend(
                            [f"[stability_mode] {item}" for item in downgraded]
                        )
                    if blocking:
                        patch_guard.violations.extend(blocking)
                elif runtime_governance_mode == "emergency":
                    downgraded = [item for item in stage_violations if _emergency_warning_violation(item)]
                    blocking = [item for item in stage_violations if item not in downgraded]
                    if downgraded:
                        patch_guard.project_warnings.extend(
                            [f"[emergency_mode] {item}" for item in downgraded]
                        )
                    if blocking:
                        patch_guard.violations.extend(blocking)
                else:
                    patch_guard.violations.extend(stage_violations)
            if design_violation_records:
                design_mode = _project_contract_enforcement_mode(
                    context.project_contract if isinstance(context.project_contract, dict) else None
                )
                design_blocking = design_mode == "strict"
                patch_guard.project_violation_records.extend(
                    [{**record, "mode": design_mode, "blocking": design_blocking} for record in design_violation_records]
                )
            verification = await self._load_patch_verification(work_item, context)
            verification = _verification_from_action_scope(verification, patch_guard.touched_files)
            repository_state = str(((work_item.payload or {}) if isinstance(work_item.payload, dict) else {}).get("repository_state") or "")
            payload = work_item.payload if isinstance(work_item.payload, dict) else {}
            target_files = _target_files_from_payload(payload)
            operator_confirmation_required = _should_block_for_operator_confirmation(
                verification,
                plan.actions,
                repository_state=repository_state,
            )
            governance_decision = evaluate_mutation_governance(
                work_item_type=work_item.type,
                target_files=target_files,
                changed_files=patch_guard.touched_files,
                operator_confirmation_required=operator_confirmation_required,
                repository_state=repository_state,
            )
            governance_decision = self._maybe_bypass_operator_confirmation(governance_decision)
            confirmation_granted = _has_operator_confirmation_grant(work_item)
            if confirmation_granted and governance_decision.requires_confirmation:
                governance_decision = MutationGovernanceDecision(
                    requires_confirmation=False,
                    mutation_class=governance_decision.mutation_class,
                    reason="operator_confirmation_granted",
                )
            if governance_decision.requires_confirmation:
                if runtime_governance_mode == "emergency" and not contains_sensitive_paths(target_files):
                    governance_decision = MutationGovernanceDecision(
                        requires_confirmation=False,
                        mutation_class=governance_decision.mutation_class,
                        reason="emergency_ship_mode",
                    )
                else:
                    await self._job_manager.fail_job(
                        prepared.job_id,
                        reason="human_review_required",
                        next_action=_operator_confirmation_next_action(verification),
                        error_kind="human_review_required",
                        input_tokens=usage_input_tokens,
                        output_tokens=usage_output_tokens,
                        actual_cost_cents=usage_cost_cents,
                        approval_state="pending",
                        status="blocked",
                        details={
                            "verification": verification.model_dump(),
                            "mutation_governance": {
                                "mutation_class": governance_decision.mutation_class,
                                "reason": governance_decision.reason,
                            },
                        },
                    )
                    return {
                        "status": "FAILED",
                        "message": "Patch execution requires operator confirmation before mutating the repository.",
                        "payload": {
                            "approval_required": True,
                            "stop_reason": "human_review_required",
                            "error": "operator_confirmation_required",
                            "actions": [a.model_dump() for a in plan.actions],
                            "verification": verification.model_dump(),
                            "touched_files": patch_guard.touched_files,
                            "mutation_governance": {
                                "mutation_class": governance_decision.mutation_class,
                                "reason": governance_decision.reason,
                            },
                        },
                        "warnings": ["requires_confirmation"],
                    }
            if not patch_guard.ok:
                if runtime_governance_mode == "stability":
                    downgraded_pg = [item for item in list(patch_guard.violations) if _stability_warning_violation(item)]
                    if downgraded_pg:
                        patch_guard = replace(
                            patch_guard,
                            project_warnings=[
                                *patch_guard.project_warnings,
                                *[f"[stability_mode] {item}" for item in downgraded_pg],
                            ],
                            violations=[item for item in patch_guard.violations if item not in downgraded_pg],
                        )
                elif runtime_governance_mode == "emergency":
                    downgraded_pg = [item for item in list(patch_guard.violations) if _emergency_warning_violation(item)]
                    if downgraded_pg:
                        patch_guard = replace(
                            patch_guard,
                            project_warnings=[
                                *patch_guard.project_warnings,
                                *[f"[emergency_mode] {item}" for item in downgraded_pg],
                            ],
                            violations=[item for item in patch_guard.violations if item not in downgraded_pg],
                        )
                if not patch_guard.ok:
                    repair_error: Exception | None = None
                    if (
                        stage_violations
                        and not stage_scope_repair_attempted
                        and self._is_stage_scope_repair_candidate(
                            work_item=work_item,
                            violations=stage_violations,
                        )
                    ):
                        stage_scope_repair_attempted = True
                        await self._job_manager.record_retry(prepared.job_id, "stage_scope_violation")
                        try:
                            plan, raw, repair_usage, repair_model_tier, repair_model_name = (
                                await self._repair_plan_after_stage_scope_violation(
                                    client=client,
                                    prepared=prepared,
                                    user_prompt=user_prompt,
                                    allowed_files=allowed_files,
                                    violations=stage_violations,
                                    work_item=work_item,
                                    contract=contract,
                                )
                            )
                        except Exception as repair_exc:
                            repair_error = repair_exc
                        else:
                            repair_input_tokens = int(
                                repair_usage.get("input_tokens") or estimate_tokens(system_prompt + user_prompt)
                            )
                            repair_output_tokens = int(repair_usage.get("output_tokens") or estimate_tokens(raw))
                            usage_input_tokens += repair_input_tokens
                            usage_output_tokens += repair_output_tokens
                            usage_cost_cents = round(
                                usage_cost_cents
                                + self._job_manager.estimate_cost_cents(
                                    repair_model_tier,
                                    repair_input_tokens,
                                    repair_output_tokens,
                                ),
                                4,
                            )
                            usage = {
                                "input_tokens": usage_input_tokens,
                                "output_tokens": usage_output_tokens,
                            }
                            attempt_tiers.append(repair_model_tier)
                            effective_model_tier = repair_model_tier
                            effective_model_name = repair_model_name
                            contract = await self._record_execution_budget(
                                context,
                                prepared_job_id=str(prepared.job_id),
                                work_item_id=str(work_item.id),
                                selected_model_tier=repair_model_tier,
                                input_tokens=repair_input_tokens,
                                output_tokens=repair_output_tokens,
                            )
                            if contract is not None and contract.budget.budget_mode == "BLOCKED":
                                next_action = self._budget_next_action(work_item)
                                await self._job_manager.fail_job(
                                    prepared.job_id,
                                    reason="run_budget_exhausted",
                                    next_action=next_action,
                                    error_kind="run_budget_exhausted",
                                    input_tokens=usage_input_tokens,
                                    output_tokens=usage_output_tokens,
                                    actual_cost_cents=usage_cost_cents,
                                    details={
                                        "attempt_tiers": attempt_tiers,
                                        "provider": self.settings.llm_provider,
                                        "model_name": repair_model_name,
                                        "budget": contract.budget.to_dict(),
                                    },
                                )
                                return self._run_budget_exhausted_result(
                                    contract=contract,
                                    prepared_job_id=str(prepared.job_id),
                                    next_action=next_action,
                                )
                            continue
                    if repair_error is not None:
                        patch_guard.violations.append(f"Automatic stage-scope repair failed: {repair_error}")
                    await self._job_manager.fail_job(
                        prepared.job_id,
                        reason="patch_guard_violation",
                        next_action="Reduce the touched file set or adjust the scoped plan before retrying.",
                        error_kind="patch_guard_violation",
                        input_tokens=usage_input_tokens,
                        output_tokens=usage_output_tokens,
                        actual_cost_cents=usage_cost_cents,
                        details={
                            "violations": patch_guard.violations,
                            "design_violation_records": design_violation_records,
                        },
                    )
                    return {
                        "status": "FAILED",
                        "message": "; ".join(patch_guard.violations),
                        "payload": {
                            "actions": [a.model_dump() for a in plan.actions],
                            "allowed_files": patch_guard.allowed_files,
                            "touched_files": patch_guard.touched_files,
                            "protected_zones": patch_guard.protected_zones,
                            "safe_zones": patch_guard.safe_zones,
                            "project_rules_applied": patch_guard.project_rules_applied,
                            "project_warnings": patch_guard.project_warnings,
                            "project_enforcement_mode": patch_guard.project_enforcement_mode,
                            "project_violation_records": patch_guard.project_violation_records,
                            "design_violation_records": design_violation_records,
                        },
                        "warnings": ["patch_guard_violation", *([] if not design_violation_records else ["design_contract_violation"])],
                    }

            total_written = 0
            changed_lines = 0
            current_action = None
            mutations_applied = False
            try:
                for current_action in plan.actions:
                    if current_action.type == "write_file":
                        if not current_action.path or current_action.content is None:
                            raise ValueError("write_file requires path and content")
                        if _contains_probable_secret_leak(current_action.content):
                            raise ValueError("secret_pattern_detected_in_output")
                        b = current_action.content.encode()
                        total_written += len(b)
                        if total_written > self.settings.codex_max_write_bytes_total:
                            raise ValueError("Write exceeds max total bytes")
                        repo.write_file(current_action.path, current_action.content)
                        mutations_applied = True
                    elif current_action.type == "delete_file":
                        if not current_action.path:
                            raise ValueError("delete_file requires path")
                        repo.delete_file(current_action.path)
                        mutations_applied = True
                    elif current_action.type == "apply_patch":
                        if not current_action.patch:
                            raise ValueError("apply_patch requires patch")
                        if _contains_probable_secret_leak(_added_patch_payload(current_action.patch)):
                            raise ValueError("secret_pattern_detected_in_output")
                        invalid_headers = self._invalid_patch_hunk_headers(current_action.patch)
                        if invalid_headers:
                            raise ValueError(
                                "Patch uses invalid unified diff hunk headers: "
                                + ", ".join(invalid_headers[:2])
                            )
                        structure_error = self._patch_structure_error(current_action.patch)
                        if structure_error:
                            raise ValueError(structure_error)
                        b = current_action.patch.encode()
                        total_written += len(b)
                        if total_written > self.settings.codex_max_write_bytes_total:
                            raise ValueError("Write exceeds max total bytes")
                        file_headers = [ln for ln in current_action.patch.splitlines() if ln.startswith("diff --git")]
                        if len(file_headers) > self.max_patch_files:
                            raise ValueError("Patch touches too many files")
                        changed_lines = sum(
                            1
                            for ln in current_action.patch.splitlines()
                            if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
                        )
                        max_patch_lines = self._max_patch_lines_for(work_item)
                        if changed_lines > max_patch_lines:
                            raise ValueError("Patch changes too many lines")
                        per_file_changes = self._parse_patch_file_stats(current_action.patch)
                        for rel_path, stats in per_file_changes.items():
                            if self._should_bypass_patch_ratio_limit(rel_path):
                                continue
                            if self._patch_change_ratio(
                                work_item,
                                rel_path,
                                additions=stats["added"],
                                deletions=stats["deleted"],
                            ) > ratio:
                                raise ValueError(f"Patch too large for {rel_path} (>{int(ratio*100)}% change)")
                        repo.apply_patch(current_action.patch)
                        mutations_applied = True
                    elif current_action.type == "note":
                        continue
            except Exception as exc:
                if (
                    not patch_repair_attempted
                    and self._is_patch_repair_candidate(
                        action=current_action,
                        error=exc,
                        mutations_applied=mutations_applied,
                    )
                ):
                    patch_repair_attempted = True
                    if self._try_deterministic_frontend_patch_recovery(
                        work_item=work_item,
                        action=current_action,
                        repo=repo,
                        allowed_files=allowed_files,
                    ):
                        if current_action is not None:
                            current_action.type = "note"
                            current_action.text = (
                                "Deterministic frontend patch recovery applied after apply_patch failure."
                            )
                            current_action.patch = None
                            current_action.content = None
                            current_action.path = None
                        continue
                    if effective_mutation_strategy == "apply_patch":
                        effective_mutation_strategy = "write_file"
                        mutation_strategy_transitions.append(
                            {
                                "from": "apply_patch",
                                "to": "write_file",
                                "reason": "patch_drift_high_risk_static_frontend",
                            }
                        )
                    await self._job_manager.record_retry(prepared.job_id, "patch_apply_error")
                    try:
                        plan, raw, repair_usage, repair_model_tier, repair_model_name = await self._repair_plan_after_patch_failure(
                            client=client,
                            prepared=prepared,
                            user_prompt=user_prompt,
                            allowed_files=allowed_files,
                            error_message=str(exc),
                            work_item=work_item,
                            contract=contract,
                        )
                    except Exception as repair_exc:
                        lowered_repair_error = str(repair_exc).lower()
                        if "patch repair output was invalid" in lowered_repair_error and isinstance(work_item.payload, dict):
                            work_item.payload["recovery_strategy"] = "write_file_preferred"
                            work_item.payload["prior_patch_failures"] = int(work_item.payload.get("prior_patch_failures") or 0) + 1
                            if not patch_repair_parse_retry_attempted:
                                patch_repair_parse_retry_attempted = True
                                await self._job_manager.record_retry(prepared.job_id, "patch_repair_output_invalid")
                                try:
                                    plan, raw, repair_usage, repair_model_tier, repair_model_name = (
                                        await self._repair_plan_after_patch_failure(
                                            client=client,
                                            prepared=prepared,
                                            user_prompt=user_prompt,
                                            allowed_files=allowed_files,
                                            error_message=str(exc),
                                            work_item=work_item,
                                            contract=contract,
                                        )
                                    )
                                except Exception as forced_repair_exc:
                                    exc = forced_repair_exc
                                else:
                                    repair_input_tokens = int(
                                        repair_usage.get("input_tokens") or estimate_tokens(system_prompt + user_prompt)
                                    )
                                    repair_output_tokens = int(repair_usage.get("output_tokens") or estimate_tokens(raw))
                                    usage_input_tokens += repair_input_tokens
                                    usage_output_tokens += repair_output_tokens
                                    usage_cost_cents = round(
                                        usage_cost_cents
                                        + self._job_manager.estimate_cost_cents(
                                            repair_model_tier,
                                            repair_input_tokens,
                                            repair_output_tokens,
                                        ),
                                        4,
                                    )
                                    usage = {
                                        "input_tokens": usage_input_tokens,
                                        "output_tokens": usage_output_tokens,
                                    }
                                    attempt_tiers.append(repair_model_tier)
                                    effective_model_tier = repair_model_tier
                                    effective_model_name = repair_model_name
                                    contract = await self._record_execution_budget(
                                        context,
                                        prepared_job_id=str(prepared.job_id),
                                        work_item_id=str(work_item.id),
                                        selected_model_tier=repair_model_tier,
                                        input_tokens=repair_input_tokens,
                                        output_tokens=repair_output_tokens,
                                    )
                                    if contract is not None and contract.budget.budget_mode == "BLOCKED":
                                        next_action = self._budget_next_action(work_item)
                                        await self._job_manager.fail_job(
                                            prepared.job_id,
                                            reason="run_budget_exhausted",
                                            next_action=next_action,
                                            error_kind="run_budget_exhausted",
                                            input_tokens=usage_input_tokens,
                                            output_tokens=usage_output_tokens,
                                            actual_cost_cents=usage_cost_cents,
                                            details={
                                                "attempt_tiers": attempt_tiers,
                                                "provider": self.settings.llm_provider,
                                                "model_name": repair_model_name,
                                                "budget": contract.budget.to_dict(),
                                            },
                                        )
                                        return self._run_budget_exhausted_result(
                                            contract=contract,
                                            prepared_job_id=str(prepared.job_id),
                                            next_action=next_action,
                                        )
                                    continue
                        exc = repair_exc
                    else:
                        repair_input_tokens = int(
                            repair_usage.get("input_tokens") or estimate_tokens(system_prompt + user_prompt)
                        )
                        repair_output_tokens = int(repair_usage.get("output_tokens") or estimate_tokens(raw))
                        usage_input_tokens += repair_input_tokens
                        usage_output_tokens += repair_output_tokens
                        usage_cost_cents = round(
                            usage_cost_cents
                            + self._job_manager.estimate_cost_cents(
                                repair_model_tier,
                                repair_input_tokens,
                                repair_output_tokens,
                            ),
                            4,
                        )
                        usage = {
                            "input_tokens": usage_input_tokens,
                            "output_tokens": usage_output_tokens,
                        }
                        attempt_tiers.append(repair_model_tier)
                        effective_model_tier = repair_model_tier
                        effective_model_name = repair_model_name
                        contract = await self._record_execution_budget(
                            context,
                            prepared_job_id=str(prepared.job_id),
                            work_item_id=str(work_item.id),
                            selected_model_tier=repair_model_tier,
                            input_tokens=repair_input_tokens,
                            output_tokens=repair_output_tokens,
                        )
                        if contract is not None and contract.budget.budget_mode == "BLOCKED":
                            next_action = self._budget_next_action(work_item)
                            await self._job_manager.fail_job(
                                prepared.job_id,
                                reason="run_budget_exhausted",
                                next_action=next_action,
                                error_kind="run_budget_exhausted",
                                input_tokens=usage_input_tokens,
                                output_tokens=usage_output_tokens,
                                actual_cost_cents=usage_cost_cents,
                                details={
                                    "attempt_tiers": attempt_tiers,
                                    "provider": self.settings.llm_provider,
                                    "model_name": repair_model_name,
                                    "budget": contract.budget.to_dict(),
                                },
                            )
                            return self._run_budget_exhausted_result(
                                contract=contract,
                                prepared_job_id=str(prepared.job_id),
                                next_action=next_action,
                            )
                        continue
                await self._job_manager.fail_job(
                    prepared.job_id,
                    reason="action_error",
                    next_action="Inspect the generated patch and rerun with a narrower scope.",
                    error_kind="action_error",
                    input_tokens=usage_input_tokens,
                    output_tokens=usage_output_tokens,
                    actual_cost_cents=usage_cost_cents,
                    details={"error": str(exc), "attempt_tiers": attempt_tiers, "model_name": effective_model_name},
                )
                return {
                    "status": "FAILED",
                    "message": f"Action error: {exc}",
                    "payload": {"actions": [a.model_dump() for a in plan.actions]},
                }
            break

        normalized_fix_failure = work_item.type == "FIX_TEST_FAILURE" and plan.status == "FAILED" and mutations_applied
        if normalized_fix_failure:
            plan.warnings.append("fix_patch_applied_despite_failed_model_status")

        effective_status = "DONE" if normalized_fix_failure else plan.status
        effective_message = (
            "Applied candidate fix patch; rerun validation to confirm the repair."
            if normalized_fix_failure
            else plan.message
        )

        diff = repo.git_diff()
        artifacts = [a.model_dump() for a in plan.artifacts]
        if diff:
            if context.patches_path:
                patch_dir = Path(context.patches_path)
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_name = f"{work_item.type.lower()}-{work_item.id}.patch"
                patch_path = patch_dir / patch_name
                patch_path.write_text(diff, encoding="utf-8")
                artifacts.append(
                    {
                        "type": "git_diff",
                        "uri": workspace_uri("patches", patch_name),
                        "path": str(patch_path),
                        "content": diff,
                    }
                )
            else:
                artifacts.append({"type": "git_diff", "content": diff})

        # Save review metrics / patch stats
        review_metrics = {}
        if plan.risk_score is not None:
            review_metrics["risk_score"] = plan.risk_score
        if plan.confidence is not None:
            review_metrics["confidence"] = plan.confidence
        if plan.patch_complexity is not None:
            review_metrics["patch_complexity"] = plan.patch_complexity
        if 'git_diff' in {a["type"] for a in artifacts}:
            review_metrics["patch_lines"] = changed_lines if 'changed_lines' in locals() else None
        combined_warnings = list(dict.fromkeys([*plan.warnings, *patch_guard.project_warnings]))
        final_status = "completed" if effective_status in {"DONE", "SKIPPED"} else "failed"
        if final_status == "completed" and content_binding_records:
            await self._sync_content_bindings(
                context=context,
                work_item=work_item,
                binding_records=content_binding_records,
            )
        if final_status == "completed":
            await self._job_manager.complete_job(
                prepared.job_id,
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                actual_cost_cents=usage_cost_cents,
                confidence_score=plan.confidence,
                details={
                    "review_metrics": review_metrics,
                    "warnings": combined_warnings,
                    "attempt_tiers": attempt_tiers,
                    "effective_model_tier": effective_model_tier,
                    "model_name": effective_model_name,
                    "mutation_strategy": {
                        "selected": selected_mutation_strategy,
                        "effective": effective_mutation_strategy,
                        "strategy_transition_reason": (
                            mutation_strategy_transitions[-1]["reason"] if mutation_strategy_transitions else None
                        ),
                        "fallback_chain": mutation_strategy_fallbacks,
                        "reasons": mutation_strategy_reasons,
                        "drift_risk_score": drift_risk_score,
                        "strategy_confidence": strategy_confidence,
                        "execution_zone": execution_zone,
                        "transitions": mutation_strategy_transitions,
                    },
                },
                status=final_status,
            )
        else:
            await self._job_manager.fail_job(
                prepared.job_id,
                reason="model_reported_failure",
                next_action="Inspect the returned plan and rerun with narrower context.",
                error_kind="model_reported_failure",
                input_tokens=usage_input_tokens,
                output_tokens=usage_output_tokens,
                actual_cost_cents=usage_cost_cents,
                details={
                    "review_metrics": review_metrics,
                    "warnings": combined_warnings,
                    "attempt_tiers": attempt_tiers,
                    "effective_model_tier": effective_model_tier,
                    "model_name": effective_model_name,
                    "mutation_strategy": {
                        "selected": selected_mutation_strategy,
                        "effective": effective_mutation_strategy,
                        "strategy_transition_reason": (
                            mutation_strategy_transitions[-1]["reason"] if mutation_strategy_transitions else None
                        ),
                        "fallback_chain": mutation_strategy_fallbacks,
                        "reasons": mutation_strategy_reasons,
                        "drift_risk_score": drift_risk_score,
                        "strategy_confidence": strategy_confidence,
                        "execution_zone": execution_zone,
                        "transitions": mutation_strategy_transitions,
                    },
                },
            )

        return {
            "status": effective_status,
            "message": effective_message,
            "payload": {
                "artifacts": artifacts,
                "warnings": combined_warnings,
                "ai_job_id": str(prepared.job_id),
                "ai_selected_tier": prepared.policy.selected_model_tier,
                "ai_effective_tier": effective_model_tier,
                "ai_attempt_tiers": attempt_tiers,
                "ai_policy": self._policy_payload(prepared.policy),
                "execution_contract": contract.to_dict() if contract is not None else None,
                "patch_guard": {
                    "allowed_files": patch_guard.allowed_files,
                    "touched_files": patch_guard.touched_files,
                    "file_budget": patch_guard.file_budget,
                    "hard_file_budget": patch_guard.hard_file_budget,
                    "protected_zones": patch_guard.protected_zones,
                    "safe_zones": patch_guard.safe_zones,
                    "project_rules_applied": patch_guard.project_rules_applied,
                    "project_warnings": patch_guard.project_warnings,
                    "project_enforcement_mode": patch_guard.project_enforcement_mode,
                    "project_violation_records": patch_guard.project_violation_records,
                },
                "review": review_metrics,
                "usage": usage,
                "mutation_strategy": {
                    "selected": selected_mutation_strategy,
                    "effective": effective_mutation_strategy,
                    "strategy_transition_reason": (
                        mutation_strategy_transitions[-1]["reason"] if mutation_strategy_transitions else None
                    ),
                    "fallback_chain": mutation_strategy_fallbacks,
                    "reasons": mutation_strategy_reasons,
                    "drift_risk_score": drift_risk_score,
                    "strategy_confidence": strategy_confidence,
                    "execution_zone": execution_zone,
                    "transitions": mutation_strategy_transitions,
                },
                "content_binding_attempted": bool(content_binding_telemetry.get("content_binding_attempted")),
                "content_binding_enabled": bool(content_binding_telemetry.get("content_binding_enabled")),
                "content_binding_fallback_used": bool(content_binding_telemetry.get("content_binding_fallback_used")),
                "layout_integrity_score": frontend_composition_telemetry.get("layout_integrity_score"),
                "responsive_safety_score": frontend_composition_telemetry.get("responsive_safety_score"),
                "overflow_risk_score": frontend_composition_telemetry.get("overflow_risk_score"),
                "typography_consistency_score": frontend_composition_telemetry.get("typography_consistency_score"),
                "visual_composition_score": frontend_composition_telemetry.get("visual_composition_score"),
                "foundation_layout_score": foundation_quality_telemetry.get("foundation_layout_score"),
                "navigation_integrity": foundation_quality_telemetry.get("navigation_integrity"),
                "responsive_shell_score": foundation_quality_telemetry.get("responsive_shell_score"),
                "design_system_score": foundation_quality_telemetry.get("design_system_score"),
                "import_resolution_attempts": import_resolution_telemetry.get("import_resolution_attempts"),
                "resolved_component_imports": import_resolution_telemetry.get("resolved_component_imports"),
                "unresolved_component_imports": import_resolution_telemetry.get("unresolved_component_imports"),
                "import_normalization_repairs": import_resolution_telemetry.get("import_normalization_repairs"),
            },
        }

    def _parse_patch_file_stats(self, patch: str) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        current: str | None = None
        for line in patch.splitlines():
            if line.startswith("+++ "):
                path = line.split(maxsplit=1)[1]
                if path.strip() == "/dev/null":
                    current = None
                    continue
                # strip leading a/ or b/
                if path.startswith(("b/", "a/")):
                    path = path[2:]
                current = path.strip()
                stats.setdefault(current, {"added": 0, "deleted": 0})
                continue
            if line.startswith("diff --git"):
                # new file header will be handled on +++ line
                continue
            if current and line and line[0] in {"+", "-"} and not line.startswith(("+++", "---")):
                key = "added" if line.startswith("+") else "deleted"
                stats[current][key] = stats[current].get(key, 0) + 1
        return stats

    def _parse_patch_changes(self, patch: str) -> dict[str, int]:
        """
        Returns mapping of rel_path -> changed lines (add+del) from a unified diff.
        """
        return {
            rel_path: file_stats["added"] + file_stats["deleted"]
            for rel_path, file_stats in self._parse_patch_file_stats(patch).items()
        }

    def _file_line_count(self, rel_path: str) -> int:
        p = (self.repo_root / rel_path).resolve()
        if not str(p).startswith(str(self.repo_root)):
            raise ValueError("Path escapes repo root")
        if not p.exists() or not p.is_file():
            return 0
        try:
            return len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            return 0

    def _build_context(
        self,
        repo: RepoTools,
        work_item: WorkItem,
        execution_contract: ExecutionContract | None = None,
    ) -> dict[str, Any]:
        """
        Deterministic minimal context selection.
        Priority:
        1) files referenced in latest diff artifact (if present)
        2) failing test file (from payload stderr/stdout)
        3) explicit paths in payload (files/paths/target_file)
        4) depth-1 local imports of already selected files
        5) small project metadata (pyproject/requirements/package.json)
        Capped by codex_max_context_bytes.
        Capped by codex_max_context_bytes.
        """
        max_bytes = self.settings.codex_max_context_bytes
        files: dict[str, str] = {}
        seen: set[str] = set()
        artifacts: dict[str, str] = {}

        def add_paths(paths: list[str]):
            nonlocal max_bytes
            new_paths = [p for p in paths if p and p not in seen]
            if not new_paths or max_bytes <= 0:
                return
            chunk = repo.read_files(new_paths, max_bytes)
            for k, v in chunk.items():
                if max_bytes <= 0:
                    break
                files[k] = v
                seen.add(k)
                max_bytes -= len(v.encode())

        payload = work_item.payload or {}
        target_files = (
            list(execution_contract.target_files)
            if execution_contract is not None and execution_contract.target_files
            else _target_files_from_payload(payload)
        )
        if target_files:
            add_paths(target_files)
        elif execution_contract is not None and execution_contract.allowed_files:
            add_paths(list(execution_contract.allowed_files))

        # 1) Diff artifact file paths (highest priority for fixes)
        diff_art = None
        if isinstance(payload.get("artifacts"), list):
            for art in payload["artifacts"]:
                if not isinstance(art, dict):
                    continue
                if art.get("type") in {"git_diff", "diff_summary"} and isinstance(art.get("content"), str):
                    artifacts[art["type"]] = art["content"]
                    diff_art = art["content"]
                    break
        if diff_art:
            diff_paths = self._paths_from_diff(diff_art)
            add_paths(diff_paths)

        # 2) Failing test file from stderr/stdout stack traces
        payload = work_item.payload or {}
        err_text = (payload.get("stderr") or "") + "\n" + (payload.get("stdout") or "")
        stack_paths = re.findall(r'File "([^"]+)"', err_text)
        add_paths(stack_paths)

        # 3) Explicit paths from payload hints
        for key in ["file", "filepath", "path", "target_file"]:
            val = payload.get(key)
            if isinstance(val, str):
                add_paths([val])
            if isinstance(val, list):
                add_paths([x for x in val if isinstance(x, str)])
        if isinstance(payload.get("files"), list):
            add_paths([x for x in payload["files"] if isinstance(x, str)])
        if isinstance(payload.get("related_files"), list):
            add_paths([x for x in payload["related_files"] if isinstance(x, str)])
        if isinstance(payload.get("failing_test_files"), list):
            add_paths([x for x in payload["failing_test_files"] if isinstance(x, str)])
        if execution_contract is not None:
            add_paths(list(execution_contract.related_files))

        # 4) Depth-1 local imports from already added Python files
        import_candidates = [p for p in list(files.keys()) if p.endswith(".py")]
        resolved_imports: list[str] = []
        for path in import_candidates:
            try:
                content = files[path]
            except KeyError:
                continue
            for imp in re.findall(r"^(?:from|import) ([\\w\\.]+)", content, flags=re.MULTILINE):
                resolved = self._resolve_local_import(imp)
                if resolved:
                    resolved_imports.append(resolved)
        add_paths(resolved_imports)

        # 5) Small project metadata (lowest priority)
        add_paths(
            [
                "pyproject.toml",
                "requirements.txt",
                "package.json",
                "poetry.lock",
                "README.md",
            ]
        )

        return {
            "files": files,
            "meta": {
                "context_bytes": self.settings.codex_max_context_bytes - max_bytes,
                "artifact_types": list(artifacts.keys()),
            },
            "artifacts": artifacts,
        }

    async def _load_graph_context(self, work_item: WorkItem) -> dict[str, Any] | None:
        try:
            async with SessionLocal() as session:
                context = await build_graph_context(
                    session,
                    entity_type="work_item",
                    entity_id=work_item.id,
                    project_id=work_item.project_id,
                    max_depth=EXECUTOR_CONTEXT_LIMITS.max_depth,
                    limits=EXECUTOR_CONTEXT_LIMITS,
                )
            return compact_graph_context(context)
        except Exception:
            return None

    async def _load_patch_verification(
        self,
        work_item: WorkItem,
        context: RunContext,
    ) -> RunPatchVerificationSummary | None:
        plan_snapshot = context.plan_snapshot if isinstance(context.plan_snapshot, dict) else {}
        planned_files = (
            list(context.execution_contract.allowed_files)
            if context.execution_contract is not None and context.execution_contract.allowed_files
            else [
                path
                for path in plan_snapshot.get("expected_files", [])
                if isinstance(path, str) and path.strip()
            ]
        )
        planned_steps = [
            step.get("title")
            for step in plan_snapshot.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("title"), str) and step.get("title").strip()
        ]
        goal = plan_snapshot.get("goal")
        confidence_score = plan_snapshot.get("confidence_score")
        try:
            async with SessionLocal() as session:
                run = await session.get(Run, context.run_id)
                if run is None:
                    return None
                _, verification = await build_run_patch_plan_and_verification(
                    session,
                    tenant_id=work_item.tenant_id,
                    run=run,
                    goal=goal if isinstance(goal, str) and goal.strip() else None,
                    planned_steps=planned_steps,
                    planned_files=planned_files,
                    confidence_score=confidence_score if isinstance(confidence_score, (int, float)) else None,
                )
                return verification
        except Exception:
            return None

    def _resolve_local_import(self, module: str) -> str | None:
        """
        Resolve a python module string to a relative file path if it exists in repo root.
        Only depth-1 (no recursion).
        """
        candidate = module.replace(".", "/") + ".py"
        p = (self.repo_root / candidate).resolve()
        if str(p).startswith(str(self.repo_root)) and p.exists() and p.is_file():
            # return relative path from repo root
            return str(p.relative_to(self.repo_root))
        return None

    def _paths_from_diff(self, diff: str) -> list[str]:
        paths: list[str] = []
        for line in diff.splitlines():
            if line.startswith("+++ "):
                path = line.split(maxsplit=1)[1]
                if path.strip() == "/dev/null":
                    continue
                if path.startswith(("b/", "a/")):
                    path = path[2:]
                paths.append(path.strip())
        return paths

    def _invalid_patch_hunk_headers(self, patch: str) -> list[str]:
        invalid_headers: list[str] = []
        for line in patch.splitlines():
            if line.startswith("@@") and not _UNIFIED_DIFF_HUNK_RE.match(line):
                invalid_headers.append(line.strip())
        return invalid_headers

    def _patch_structure_error(self, patch: str) -> str | None:
        lines = patch.splitlines()
        has_old_header = any(line.startswith("--- ") for line in lines)
        has_new_header = any(line.startswith("+++ ") for line in lines)
        has_hunks = any(line.startswith("@@") for line in lines)
        if has_hunks and not (has_old_header and has_new_header):
            return "Patch is missing file headers (---/+++) before diff hunks."
        return None

    def _try_deterministic_frontend_patch_recovery(
        self,
        *,
        work_item: WorkItem,
        action: Any | None,
        repo: RepoTools,
        allowed_files: list[str],
    ) -> bool:
        if work_item.type != "CODE_FRONTEND":
            return False
        if action is None or getattr(action, "type", None) != "apply_patch":
            return False
        rel_path = str(getattr(action, "path", "") or "").strip()
        patch_text = getattr(action, "patch", None)
        if not rel_path or not isinstance(patch_text, str) or not patch_text.strip():
            return False
        if allowed_files and rel_path not in allowed_files:
            return False
        if Path(rel_path).suffix.lower() not in {".html", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"}:
            return False
        return self._apply_patch_by_hunk_replacement(repo=repo, rel_path=rel_path, patch_text=patch_text)

    def _apply_patch_by_hunk_replacement(self, *, repo: RepoTools, rel_path: str, patch_text: str) -> bool:
        normalized_patch = patch_text if patch_text.endswith("\n") else f"{patch_text}\n"
        lines = normalized_patch.splitlines()
        hunks: list[tuple[str, str]] = []
        in_hunk = False
        old_lines: list[str] = []
        new_lines: list[str] = []
        for line in lines:
            if line.startswith("@@"):
                if in_hunk:
                    hunks.append(("".join(old_lines), "".join(new_lines)))
                    old_lines = []
                    new_lines = []
                in_hunk = True
                continue
            if not in_hunk:
                continue
            if line.startswith(("diff --git ", "--- ", "+++ ")):
                continue
            marker = line[:1] if line else ""
            body = line[1:] if marker in {" ", "+", "-"} else line
            rendered = f"{body}\n"
            if marker in {" ", "-"}:
                old_lines.append(rendered)
            if marker in {" ", "+"}:
                new_lines.append(rendered)
        if in_hunk:
            hunks.append(("".join(old_lines), "".join(new_lines)))
        if not hunks:
            return False

        target_path = (repo.root / rel_path).resolve()
        repo_root = repo.root.resolve()
        if not str(target_path).startswith(str(repo_root)):
            return False
        if not target_path.exists() or not target_path.is_file():
            return False

        text = target_path.read_text(encoding="utf-8")
        cursor = 0
        applied = 0
        for old_block, new_block in hunks:
            if not old_block:
                continue
            idx = text.find(old_block, cursor)
            if idx < 0:
                idx = text.find(old_block)
                if idx < 0:
                    return False
            text = f"{text[:idx]}{new_block}{text[idx + len(old_block):]}"
            cursor = idx + len(new_block)
            applied += 1
        if applied == 0:
            return False
        repo.write_file(rel_path, text)
        return True

    def _is_patch_repair_candidate(
        self,
        *,
        action: Any | None,
        error: Exception,
        mutations_applied: bool,
    ) -> bool:
        if mutations_applied or action is None or getattr(action, "type", None) != "apply_patch":
            return False
        patch = getattr(action, "patch", None)
        if not isinstance(patch, str) or not patch.strip():
            return False
        if self._patch_structure_error(patch):
            return True
        if self._invalid_patch_hunk_headers(patch):
            return True
        lowered = str(error).lower()
        return (
            "patch with only garbage" in lowered
            or "corrupt patch" in lowered
            or "patch fragment without header" in lowered
            or "patch does not apply" in lowered
            or "patch check failed" in lowered
            or "patch apply failed" in lowered
            or "error: patch failed:" in lowered
        )

    def _is_stage_scope_repair_candidate(
        self,
        *,
        work_item: WorkItem,
        violations: list[str],
    ) -> bool:
        if not violations:
            return False
        if "PLAN" in work_item.type:
            return True
        if work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            return True
        if work_item.type == "WRITE_TESTS":
            return any("WRITE_TESTS may only modify Python test files" in violation for violation in violations)
        if work_item.type == "CODE_FRONTEND":
            return any(
                (
                    "CODE_FRONTEND write_file payload too large" in violation
                    or "CODE_FRONTEND mutation_strategy violation" in violation
                    or "CODE_FRONTEND structural contract violation" in violation
                )
                for violation in violations
            )
        if _is_backend_codegen_type(work_item.type):
            return any(
                ("mutation_strategy violation" in violation or "structural contract violation" in violation)
                for violation in violations
            )
        return False

    def _mutation_strategy_violations(
        self,
        *,
        work_item: WorkItem,
        selected_strategy: str,
        actions: list[Any],
    ) -> list[str]:
        if work_item.type not in {"GENESIS_FOUNDATION", "CODE_FRONTEND", "CODE_BACKEND", "GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING"}:
            return []
        # Frontend: strategy is a preference signal; only reject mixed mutation output.
        # Backend: write_file_preferred recovery is a hard override for convergence.
        mutating_types = {
            getattr(action, "type", None)
            for action in actions
            if getattr(action, "type", None) in {"write_file", "apply_patch"}
        }
        if len(mutating_types) > 1:
            return [
                f"{work_item.type} mutation_strategy violation: plan emitted mixed mutating action types (write_file and apply_patch)."
            ]
        return []

    def _enforce_feature_zone_composer(
        self,
        *,
        work_item: WorkItem,
        repo_root: Path,
        actions: list[Any],
    ) -> tuple[list[Any], list[str]]:
        if work_item.type != "CODE_FRONTEND":
            return actions, []
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        if str(payload.get("mutation_class") or "").strip().upper() != "FEATURE":
            return actions, []

        landing_rel = "apps/web/src/pages/LandingPage.vue"
        landing_path = repo_root / landing_rel
        if not landing_path.exists():
            return actions, []
        try:
            landing_content = landing_path.read_text(encoding="utf-8")
        except Exception:
            return actions, []

        zone_names = sorted({str(m.group(1) or "").strip().lower() for m in _LANDING_ZONE_MARKER_RE.finditer(landing_content)})
        if not zone_names:
            return actions, [
                "LandingPage missing required zone markers; run GENESIS_FOUNDATION repair before CODE_FRONTEND."
            ]

        task_text = " ".join(str(payload.get(key) or "").strip().lower() for key in ("task_title", "title", "goal", "task_description"))
        target_zone = "hero" if "hero" in task_text else "testimonials" if "testimonial" in task_text else "cta" if "cta" in task_text else "feature"
        if target_zone not in zone_names:
            target_zone = zone_names[0]

        component_actions = [
            action
            for action in actions
            if getattr(action, "type", None) == "write_file"
            and isinstance(getattr(action, "path", None), str)
            and "/components/landing/" in str(getattr(action, "path", "")).replace("\\", "/").lower()
            and str(getattr(action, "path", "")).replace("\\", "/").lower().endswith(".vue")
        ]
        if not component_actions:
            return actions, []

        preferred_component = component_actions[0]
        for action in component_actions:
            candidate_path = str(getattr(action, "path", "")).lower()
            if target_zone in candidate_path:
                preferred_component = action
                break
        component_file = str(getattr(preferred_component, "path", "")).replace("\\", "/")
        component_name = Path(component_file).stem
        component_tag = f"<{component_name} />"

        composed_landing = replace_zone(landing_content, target_zone, component_tag)
        updated_actions: list[Any] = []
        for action in actions:
            action_type = getattr(action, "type", None)
            path = str(getattr(action, "path", "") or "").replace("\\", "/")
            lower = path.lower()
            if action_type in {"write_file", "apply_patch"} and lower.endswith("/pages/landingpage.vue"):
                continue
            if action_type == "write_file" and "/components/landing/" in lower and path != component_file:
                # Keep feature scope tight: only selected section component is authored by model.
                continue
            updated_actions.append(action)

        updated_actions.append(Action(type="write_file", path=landing_rel, content=composed_landing))

        # Hero task hard-scope: only HeroSection component + hero zone composition block.
        if "hero" in task_text and not component_file.lower().endswith("/components/landing/herosection.vue"):
            return updated_actions, [
                "FEATURE hero task scope violation: expected HeroSection component generation for hero zone composition."
            ]
        return updated_actions, []

    def _landing_topology_from_payload(self, payload: dict[str, Any]) -> FrontendTopology:
        topology_plan = payload.get("frontend_topology_plan") if isinstance(payload.get("frontend_topology_plan"), dict) else {}
        configured = topology_plan.get("composition_zones") if isinstance(topology_plan, dict) else None
        if not isinstance(configured, list) or not configured:
            return DEFAULT_LANDING_TOPOLOGY
        default_map = {zone.zone_component: zone for zone in DEFAULT_LANDING_TOPOLOGY.zones}
        zones: list[FrontendZone] = []
        for raw in configured:
            if not isinstance(raw, str) or not raw.strip():
                continue
            component = raw.strip()
            if component in default_map:
                zones.append(default_map[component])
                continue
            zone_id = component.replace("Zone", "").strip().lower() or component.lower()
            zones.append(
                FrontendZone(
                    id=zone_id,
                    zone_component=component,
                    semantic_type=zone_id,
                    default_component=f"{component.replace('Zone', '').strip() or 'Section'}Placeholder",
                    required=True,
                )
            )
        if not zones:
            return DEFAULT_LANDING_TOPOLOGY
        return FrontendTopology(layout="landing", shell="PageShell", zones=tuple(zones))

    def _auto_normalize_landing_zone_actions(
        self,
        *,
        work_item: WorkItem,
        actions: list[Any],
    ) -> tuple[list[Any], list[str], list[str]]:
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        if work_item.type != "CODE_FRONTEND":
            return actions, [], []
        mutation_class = str(payload.get("mutation_class") or "").strip().upper()
        if mutation_class not in {"FEATURE", "POLISH"}:
            return actions, [], []
        stability_mode = _runtime_governance_mode(payload) == "stability"
        graph_topology = self._landing_topology_from_payload(payload)

        updated_actions: list[Any] = []
        warnings: list[str] = []
        violations: list[str] = []
        for action in actions:
            if getattr(action, "type", None) != "write_file":
                updated_actions.append(action)
                continue
            path = str(getattr(action, "path", "") or "").strip().replace("\\", "/").lower()
            content = getattr(action, "content", None)
            if not (path.endswith("/pages/landingpage.vue") and isinstance(content, str)):
                updated_actions.append(action)
                continue
            topology_signature = _landing_topology_signature(content)
            required_zone_components = [zone.zone_component for zone in graph_topology.zones if zone.required]
            missing_zones = [zone for zone in required_zone_components if zone not in topology_signature["zone_components"]]
            if not missing_zones:
                updated_actions.append(action)
                continue
            normalized_content, normalize_warnings, ok = normalize_landing_graph_content(
                content=content,
                topology=graph_topology,
                stability_mode=stability_mode,
            )
            warnings.extend(normalize_warnings)
            if not ok:
                violations.append("LandingPage normalization failed: unable to restore required zones.")
                updated_actions.append(action)
                continue
            updated_actions.append(Action(type="write_file", path=str(getattr(action, "path", "")), content=normalized_content))
        return updated_actions, warnings, violations

    def _frontend_writefile_violations(self, *, work_item: WorkItem, actions: list[Any]) -> list[str]:
        if work_item.type not in {"CODE_FRONTEND", "GENESIS_FOUNDATION"} or not _is_static_frontend_scope(work_item.payload):
            return []
        violations: list[str] = []
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        task_text = " ".join(
            str(payload.get(key) or "").strip().lower()
            for key in ("task_title", "title", "goal", "task_description")
        )
        testimonials_task = "testimonial" in task_text
        hero_cta_task = ("hero" in task_text) and ("cta" in task_text or "call-to-action" in task_text or "button" in task_text)
        topology_plan = (
            (work_item.payload or {}).get("frontend_topology_plan")
            if isinstance(work_item.payload, dict)
            else None
        )
        planned_components = set()
        if isinstance(topology_plan, dict) and isinstance(topology_plan.get("component_files"), list):
            planned_components = {
                str(path).strip().lower().replace("\\", "/")
                for path in topology_plan.get("component_files", [])
                if isinstance(path, str) and path.strip()
            }
        touched_write_paths = {
            str(getattr(action, "path", "") or "").strip().lower().replace("\\", "/")
            for action in actions
            if getattr(action, "type", None) == "write_file"
        }
        protected_shells = {
            "apps/web/src/app.vue",
            "apps/web/src/layouts/pageshell.vue",
        }
        task_source = str(payload.get("task_source") or "").strip().lower()
        repository_state = str(payload.get("repository_state") or "").strip().upper()
        mutation_class = str(payload.get("mutation_class") or "").strip().upper()
        stability_mode = _runtime_governance_mode(payload) == "stability"
        maturity_registry = _primitive_maturity_registry(payload)
        feature_mode = (
            work_item.type == "CODE_FRONTEND"
            and task_source not in {"genesis", "genesis_setup", "foundation_setup", "base_task"}
            and not task_source.startswith("genesis.")
            and repository_state not in {"GENESIS", "EARLY_BUILD"}
        )
        landing_mode = mutation_class if mutation_class in {"FEATURE", "POLISH", "RECOVERY"} else ("FEATURE" if feature_mode else "")

        required_landing_zones = list(_LANDING_ZONE_COMPONENTS)
        topology_plan = payload.get("frontend_topology_plan") if isinstance(payload.get("frontend_topology_plan"), dict) else None
        if isinstance(topology_plan, dict):
            composition_zones = topology_plan.get("composition_zones")
            if isinstance(composition_zones, list):
                for zone in composition_zones:
                    if not isinstance(zone, str):
                        continue
                    cleaned = zone.strip()
                    if cleaned and cleaned not in required_landing_zones:
                        required_landing_zones.append(cleaned)

        zone_completion_violations = self._validate_zone_replacement_completion(
            work_item=work_item,
            actions=actions,
            testimonials_task=testimonials_task,
        )
        violations.extend(zone_completion_violations)

        for action in actions:
            if getattr(action, "type", None) != "write_file":
                continue
            content = getattr(action, "content", None)
            path = getattr(action, "path", None) or "unknown"
            if not isinstance(content, str):
                continue
            size = len(content.encode("utf-8"))
            if size > MAX_FRONTEND_WRITE_FILE_BYTES:
                violations.append(
                    f"CODE_FRONTEND write_file payload too large for {path} ({size} bytes > {MAX_FRONTEND_WRITE_FILE_BYTES}). "
                    "Use minimal apply_patch hunks instead of full-file rewrites."
                )
            normalized_path = str(path).strip().lower().replace("\\", "/")
            if feature_mode and "/src/pages/" in normalized_path and not normalized_path.endswith("/pages/landingpage.vue"):
                violations.append(
                    f"CODE_FRONTEND composition zone violation in {path}: feature tasks may not create or replace isolated pages; mutate LandingPage composition zones and section components."
                )
            if normalized_path in protected_shells and landing_mode in {"FEATURE", "POLISH", "RECOVERY"}:
                violations.append(
                    f"CODE_FRONTEND foundation topology violation in {path}: {landing_mode.lower()} tasks may not fully replace App.vue or PageShell.vue."
                )
            if testimonials_task and normalized_path.endswith("/pages/landingpage.vue") and "<TestimonialsPlaceholder" in content:
                # Handled by semantic zone replacement validator to keep recovery deterministic.
                pass
            if landing_mode in {"FEATURE", "POLISH", "RECOVERY"} and normalized_path.endswith("/pages/landingpage.vue"):
                topology = _landing_topology_signature(content)
                missing_zones = [zone for zone in required_landing_zones if zone not in topology["zone_components"]]
                if not bool(topology["has_page_shell"]) and not (
                    landing_mode in {"FEATURE", "POLISH"} and _runtime_governance_mode(payload) == "stability"
                ):
                    violations.append(
                        f"CODE_FRONTEND foundation topology violation in {path}: LandingPage shell must preserve PageShell."
                    )
                if missing_zones:
                    violations.append(
                        f"CODE_FRONTEND composition zone violation in {path}: LandingPage composition zones must be preserved ({', '.join(missing_zones)} missing)."
                    )
                if "router-view" in content.lower() and landing_mode == "FEATURE":
                    violations.append(
                        f"CODE_FRONTEND foundation topology violation in {path}: feature tasks may not alter routing topology inside LandingPage composition."
                    )
                if landing_mode == "POLISH":
                    removed_components = [zone for zone in required_landing_zones if f"<{zone}" not in content]
                    if removed_components:
                        violations.append(
                            f"CODE_FRONTEND polish authority violation in {path}: polish tasks may not remove composition graph nodes ({', '.join(removed_components)} missing)."
                        )
                if landing_mode == "RECOVERY":
                    looks_minimal = ("<main" in content.lower()) and ("<PageShell" not in content)
                    if looks_minimal:
                        violations.append(
                            f"CODE_FRONTEND recovery topology violation in {path}: recovery tasks may not replace LandingPage with minimal topology."
                        )
            if testimonials_task and normalized_path.endswith("/components/landing/testimonialssection.vue"):
                required_primitives = ("SectionContainer", "SectionHeading", "ContentGrid", "TestimonialCard")
                used_primitives = [name for name in required_primitives if f"<{name}" in content]
                if stability_mode:
                    unverified = [name for name in used_primitives if not _primitive_is_verified_visual_or_higher(name, maturity_registry)]
                    if unverified:
                        violations.append(
                            f"CODE_FRONTEND primitive composition violation in {path}: stability mode forbids unverified primitives ({', '.join(unverified)}). "
                            "Use self-contained Tailwind cards unless primitive maturity is verified_visual or production_ready."
                        )
                else:
                    missing_primitives = [name for name in required_primitives if name not in used_primitives]
                    if missing_primitives:
                        violations.append(
                            f"CODE_FRONTEND primitive composition violation in {path}: testimonials sections must compose governed primitives ({', '.join(missing_primitives)} missing)."
                        )
            line_count = content.count("\n") + (1 if content else 0)
            has_governed_import = "components/governed/" in content or "components\\\\governed\\\\" in content
            used_components = set(_COMPONENT_TAG_RE.findall(content))
            has_governed_component_usage = bool(used_components & _GOVERNED_COMPONENT_HINTS)
            section_count = len(re.findall(r"<section\b", content, flags=re.IGNORECASE))
            repeated_inline_sections = section_count >= 6
            if (
                normalized_path in _FRONTEND_ROOT_FILES
                and size > MAX_FRONTEND_ROOT_MONOLITH_BYTES
                and line_count > MAX_FRONTEND_ROOT_MONOLITH_LINES
                and len(_COMPONENT_TAG_RE.findall(content)) < 3
            ):
                violations.append(
                    f"CODE_FRONTEND structural contract violation in {path}: dense single-file root output "
                    f"({line_count} lines, {size} bytes) exceeds monolith threshold. "
                    "Extract sections into component files and keep root composition-only."
                )
            if (
                normalized_path in _FRONTEND_ROOT_FILES
                and line_count > 180
                and not has_governed_import
                and not has_governed_component_usage
            ):
                violations.append(
                    f"CODE_FRONTEND structural contract violation in {path}: large root page ({line_count} lines) "
                    "must compose from governed components in src/components/governed/."
                )
            if (
                normalized_path in _FRONTEND_ROOT_FILES
                and repeated_inline_sections
                and not has_governed_component_usage
            ):
                violations.append(
                    f"CODE_FRONTEND structural contract violation in {path}: repeated inline section patterns detected "
                    f"({section_count} <section> blocks) without governed component composition."
                )
            if (
                normalized_path in _FRONTEND_ROOT_FILES
                and size > MAX_FRONTEND_ROOT_MONOLITH_BYTES
                and planned_components
                and not (touched_write_paths & planned_components)
                ):
                    violations.append(
                        f"CODE_FRONTEND structural contract violation in {path}: planned topology requires componentized output "
                        "but no planned component files were written."
                    )
            if _EMPTY_CTA_RE.search(content):
                violations.append(
                    f"CODE_FRONTEND feature materialization violation in {path}: empty <PrimaryButton> insertion is not allowed."
                )

        mutating_payload = ""
        for action in actions:
            action_type = getattr(action, "type", None)
            if action_type == "apply_patch" and isinstance(getattr(action, "patch", None), str):
                mutating_payload += "\n" + _added_patch_payload(action.patch)
            elif action_type == "write_file" and isinstance(getattr(action, "content", None), str):
                mutating_payload += "\n" + action.content

        if hero_cta_task and mutating_payload.strip():
            if _EMPTY_CTA_RE.search(mutating_payload):
                violations.append(
                    "CODE_FRONTEND feature materialization violation: empty PrimaryButton markup detected in hero/CTA task."
                )
            meaningful_markers = [
                "<HeroSection",
                "<section",
                "<h1",
                "<h2",
                "Get Started",
                "Request Demo",
            ]
            has_non_empty_cta = bool(_NON_EMPTY_CTA_RE.search(mutating_payload))
            has_material_structure = any(marker.lower() in mutating_payload.lower() for marker in meaningful_markers)
            added_nontrivial_lines = [
                line for line in mutating_payload.splitlines()
                if line.strip() and not line.strip().startswith(("<!--", "//", "/*", "*"))
            ]
            if (not has_non_empty_cta) or (not has_material_structure) or len(added_nontrivial_lines) < 4:
                violations.append(
                    "CODE_FRONTEND feature materialization violation: hero/CTA task produced negligible or non-perceptible UI delta."
                )
        return violations

    def _validate_zone_replacement_completion(
        self,
        *,
        work_item: WorkItem,
        actions: list[Any],
        testimonials_task: bool,
    ) -> list[str]:
        if work_item.type != "CODE_FRONTEND" or not testimonials_task:
            return []
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        mutation_class = str(payload.get("mutation_class") or "FEATURE").strip().upper()
        if mutation_class != "FEATURE":
            return []

        violations: list[str] = []
        writes_by_path: dict[str, str] = {}
        for action in actions:
            if getattr(action, "type", None) != "write_file":
                continue
            path = str(getattr(action, "path", "") or "").replace("\\", "/").strip()
            content = getattr(action, "content", None)
            if path and isinstance(content, str):
                writes_by_path[path.lower()] = content

        landing_path = "apps/web/src/pages/landingpage.vue"
        landing = writes_by_path.get(landing_path)
        if not landing:
            return violations

        if "<TestimonialsPlaceholder" in landing:
            violations.append(
                "CODE_FRONTEND incomplete zone replacement in apps/web/src/pages/LandingPage.vue: "
                "TestimonialsPlaceholder must be removed for FEATURE testimonials tasks."
            )

        mounted = bool(re.search(r"<TestimonialsSection\b", landing))
        if not mounted:
            violations.append(
                "CODE_FRONTEND incomplete zone replacement in apps/web/src/pages/LandingPage.vue: "
                "TestimonialsSection must be mounted."
            )

        in_zone = bool(
            re.search(
                r"<TestimonialsZone\b[^>]*>[\s\S]*?<TestimonialsSection\b",
                landing,
                flags=re.IGNORECASE,
            )
        )
        if mounted and not in_zone:
            violations.append(
                "CODE_FRONTEND incomplete zone replacement in apps/web/src/pages/LandingPage.vue: "
                "TestimonialsSection must be mounted inside TestimonialsZone."
            )

        has_import = bool(
            re.search(
                r"import\s+TestimonialsSection\s+from\s+['\"][^'\"]*TestimonialsSection\.vue['\"]",
                landing,
            )
        )
        if mounted and not has_import:
            violations.append(
                "CODE_FRONTEND incomplete zone replacement in apps/web/src/pages/LandingPage.vue: "
                "TestimonialsSection import is missing."
            )

        component_path = "apps/web/src/components/landing/testimonialssection.vue"
        component_content = writes_by_path.get(component_path)
        target_files = payload.get("target_files") if isinstance(payload.get("target_files"), list) else []
        target_lower = {str(item).strip().lower().replace("\\", "/") for item in target_files if isinstance(item, str)}
        component_reachable = bool(
            mounted and (
                component_content is not None
                or component_path in target_lower
            )
        )
        if mounted and not component_reachable:
            violations.append(
                "CODE_FRONTEND incomplete zone replacement in apps/web/src/pages/LandingPage.vue: "
                "TestimonialsSection component is not reachable from LandingPage mutation graph."
            )

        if component_content is not None:
            has_quote = "quote" in component_content.lower()
            has_name = "name" in component_content.lower()
            has_role = ("role" in component_content.lower()) or ("company" in component_content.lower())
            has_cards = bool(
                re.search(r"v-for\s*=\s*['\"][^'\"]*testimonial", component_content, flags=re.IGNORECASE)
            ) or len(re.findall(r"<article\b", component_content, flags=re.IGNORECASE)) >= 3
            if not (has_quote and has_name and has_role and has_cards):
                violations.append(
                    "CODE_FRONTEND incomplete zone replacement in apps/web/src/components/landing/TestimonialsSection.vue: "
                    "rendered testimonial content is incomplete (require visible quote/name/role cards)."
                )
        return violations

    def _normalize_frontend_import_actions(
        self,
        *,
        work_item: WorkItem,
        repo_root: Path,
        actions: list[Any],
    ) -> tuple[list[Any], dict[str, Any], list[str]]:
        telemetry: dict[str, Any] = {
            "import_resolution_attempts": 0,
            "resolved_component_imports": [],
            "unresolved_component_imports": [],
            "import_normalization_repairs": 0,
        }
        if work_item.type not in {"FIX_TEST_FAILURE", "FIX_FRONTEND_SYNTAX"}:
            return actions, telemetry, []

        updated_actions: list[Any] = []
        for action in actions:
            if getattr(action, "type", None) != "write_file":
                updated_actions.append(action)
                continue
            path = str(getattr(action, "path", "") or "").strip().replace("\\", "/")
            content = getattr(action, "content", None)
            if not (path.endswith(".vue") and isinstance(content, str) and path.startswith("apps/web/")):
                updated_actions.append(action)
                continue
            normalized = normalize_frontend_imports(
                repo_root=repo_root,
                importing_file=path,
                content=content,
            )
            telemetry["import_resolution_attempts"] = int(telemetry["import_resolution_attempts"]) + int(normalized.import_resolution_attempts)
            telemetry["import_normalization_repairs"] = int(telemetry["import_normalization_repairs"]) + int(normalized.import_normalization_repairs)
            telemetry["resolved_component_imports"] = sorted(
                set(telemetry["resolved_component_imports"]) | set(normalized.resolved_component_imports)
            )
            telemetry["unresolved_component_imports"] = sorted(
                set(telemetry["unresolved_component_imports"]) | set(normalized.unresolved_component_imports)
            )
            updated_actions.append(
                Action(type="write_file", path=path, content=normalized.content)
            )

        violations: list[str] = []
        if telemetry["unresolved_component_imports"]:
            unresolved = ", ".join(telemetry["unresolved_component_imports"])
            violations.append(
                f"Frontend import normalization could not resolve components: {unresolved}."
            )
        return updated_actions, telemetry, violations

    def _backend_writefile_violations(self, *, work_item: WorkItem, actions: list[Any]) -> list[str]:
        if not _is_backend_codegen_type(work_item.type):
            return []
        payload = work_item.payload if isinstance(work_item.payload, dict) else {}
        target_files = _target_files_from_payload(payload)
        normalized_targets = {path.strip().lower().replace("\\", "/") for path in target_files if isinstance(path, str) and path.strip()}
        if not (normalized_targets & _BACKEND_ROOT_FILES):
            return []
        topology_plan = payload.get("backend_topology_plan") if isinstance(payload.get("backend_topology_plan"), dict) else None
        planned_module_files = set()
        if isinstance(topology_plan, dict):
            module_files = topology_plan.get("module_files")
            if isinstance(module_files, dict):
                planned_module_files = {
                    str(path).strip().lower().replace("\\", "/")
                    for path in module_files.values()
                    if isinstance(path, str) and path.strip()
                }
        touched_write_paths = {
            str(getattr(action, "path", "") or "").strip().lower().replace("\\", "/")
            for action in actions
            if getattr(action, "type", None) == "write_file"
        }
        violations: list[str] = []
        for action in actions:
            if getattr(action, "type", None) != "write_file":
                continue
            content = getattr(action, "content", None)
            path = str(getattr(action, "path", "") or "").strip()
            if not isinstance(content, str):
                continue
            normalized_path = path.lower().replace("\\", "/")
            line_count = content.count("\n") + (1 if content else 0)
            if normalized_path in _BACKEND_ROOT_FILES and line_count > 280:
                violations.append(
                    f"{work_item.type} structural contract violation in {path}: dense root backend module "
                    f"({line_count} lines) exceeds bounded topology threshold. Split into route/service/repository modules."
                )
            if (
                normalized_path in _BACKEND_ROOT_FILES
                and line_count > 180
                and planned_module_files
                and not (touched_write_paths & planned_module_files)
            ):
                violations.append(
                    f"{work_item.type} structural contract violation in {path}: planned backend topology requires modular output "
                    "but no planned route/service/repository/schema files were written."
                )
        return violations

    def _content_binding_pass(
        self,
        *,
        work_item: WorkItem,
        actions: list[Any],
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
        if work_item.type != "CODE_FRONTEND":
            return [], [], {
                "content_binding_attempted": False,
                "content_binding_enabled": False,
                "content_binding_fallback_used": False,
            }
        violations: list[str] = []
        binding_records: list[dict[str, Any]] = []
        binding_enabled = self._content_binding_enabled(work_item)
        attempted = False
        fallback_used = False
        for action in actions:
            if getattr(action, "type", None) != "write_file":
                continue
            path = str(getattr(action, "path", "") or "").strip()
            content = getattr(action, "content", None)
            if not path or not isinstance(content, str):
                continue
            suffix = Path(path).suffix.lower()
            # Only rewrite Vue templates. Raw HTML entrypoints (for example index.html)
            # are not compiled as Vue templates, so ContentSlot tags render as empty custom elements.
            if suffix != ".vue":
                continue
            if not binding_enabled:
                if "<ContentSlot" in content:
                    attempted = True
                    fallback_used = True
                    action.content = self._strip_content_slots_to_plain_text(content)
                continue
            try:
                attempted = True
                literals = extract_literals(content)
            except Exception:
                # Content extraction must never block code delivery. Keep original component text.
                fallback_used = True
                continue
            if not literals:
                continue
            try:
                bindings = build_binding_registry(rel_path=path, literals=literals)
                rewritten = rewrite_with_content_slots(content, bindings)
                binding_violations = validate_binding_rewrite(rewritten.content, bindings)
                if binding_violations:
                    # Fallback-safe default: preserve original component content with inline text.
                    fallback_used = True
                    continue
                action.content = rewritten.content
                for entry in bindings:
                    if entry.key not in rewritten.applied_keys:
                        continue
                    binding_records.append(
                        {
                            "environment": "PREVIEW",
                            "key": entry.key,
                            "type": "text",
                            "value": entry.value,
                            "source": "runtime",
                        }
                    )
            except Exception:
                # Fallback-safe default: preserve original component content with inline text.
                fallback_used = True
                continue
        return violations, binding_records, {
            "content_binding_attempted": attempted,
            "content_binding_enabled": binding_enabled,
            "content_binding_fallback_used": fallback_used,
        }

    def _content_binding_enabled(self, work_item: WorkItem) -> bool:
        if self.settings.content_binding_enabled:
            return True
        payload_value = getattr(work_item, "payload", None)
        payload = payload_value if isinstance(payload_value, dict) else {}
        return bool(payload.get("content_binding_enabled"))

    def _strip_content_slots_to_plain_text(self, content: str) -> str:
        def _replacement(match: re.Match[str]) -> str:
            attrs = match.group(1) or ""
            bound = _SLOT_FALLBACK_BOUND_RE.search(attrs)
            if bound:
                expr = (bound.group(1) or "").strip()
                if expr:
                    return f"{{{{ {expr} }}}}"
            literal = _SLOT_FALLBACK_LITERAL_RE.search(attrs)
            if literal:
                value = (literal.group(1) or "").strip()
                if value:
                    return value
            return ""

        return _CONTENT_SLOT_TAG_RE.sub(_replacement, content)

    async def _sync_content_bindings(
        self,
        *,
        context: RunContext,
        work_item: WorkItem,
        binding_records: list[dict[str, Any]],
    ) -> None:
        if not binding_records:
            return
        async with SessionLocal() as session:
            seen: set[str] = set()
            for record in binding_records:
                key = str(record.get("key") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                await upsert_content_item(
                    session,
                    tenant_id=work_item.tenant_id,
                    workspace_id=getattr(context, "workspace_id", None),
                    project_id=work_item.project_id,
                    environment=str(record.get("environment") or "PREVIEW"),
                    key=key,
                    content_type=str(record.get("type") or "text"),
                    value=record.get("value"),
                    source=str(record.get("source") or "runtime"),
                    updated_by="runtime.codex_executor",
                    status="DRAFT",
                )

    def _extract_added_patch_content(self, patch: str) -> str:
        added_lines: list[str] = []
        for line in patch.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                added_lines.append(line[1:])
        return "\n".join(added_lines)

    def _design_validation_violations(
        self,
        *,
        work_item: WorkItem,
        actions: list[Any],
        project_contract: dict[str, Any] | None,
    ) -> list[str]:
        return [record["message"] for record in self._design_validation_records(
            work_item=work_item,
            actions=actions,
            project_contract=project_contract,
        )]

    def _design_validation_records(
        self,
        *,
        work_item: WorkItem,
        actions: list[Any],
        project_contract: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if work_item.type != "CODE_FRONTEND" or not isinstance(project_contract, dict):
            return []
        design_packet = _design_context_packet(project_contract)
        if not design_packet:
            return []
        enforcement = (
            project_contract.get("enforcement") if isinstance(project_contract.get("enforcement"), dict) else {}
        )
        enforce_inline = bool(enforcement.get("disallow_inline_styles"))
        enforce_tokens = bool(enforcement.get("enforce_color_tokens"))
        allowed_components = {
            str(name).strip()
            for name in design_packet.get("allowed_components", [])
            if isinstance(name, str) and str(name).strip()
        }
        if self._content_binding_enabled(work_item):
            allowed_components.add("ContentSlot")
        if not enforce_inline and not enforce_tokens and not allowed_components:
            return []

        allowed_hex = _flatten_token_colors(
            design_packet.get("token_registry") if isinstance(design_packet.get("token_registry"), dict) else {}
        )
        enforcement_allowed_hex = enforcement.get("allowed_hex_values") if isinstance(enforcement.get("allowed_hex_values"), list) else []
        for value in enforcement_allowed_hex:
            if isinstance(value, str) and value.strip():
                allowed_hex.add(value.strip().lower())
        rewrite_map = _build_design_token_rewrite_map(project_contract=project_contract, allowed_hex=allowed_hex)
        bootstrap_mode = _is_bootstrap_or_genesis_scope(work_item)
        recovery_strategy = str(((work_item.payload or {}) if isinstance(work_item.payload, dict) else {}).get("recovery_strategy") or "").strip().lower()
        records: list[dict[str, Any]] = []
        for action in actions:
            action_type = getattr(action, "type", None)
            path = getattr(action, "path", None) or "unknown"
            content = ""
            if action_type == "write_file":
                raw = getattr(action, "content", None)
                if isinstance(raw, str):
                    content = raw
            elif action_type == "apply_patch":
                patch = getattr(action, "patch", None)
                if isinstance(patch, str):
                    content = self._extract_added_patch_content(patch)
            if not content:
                continue
            normalized_content, token_rewrites = _normalize_frontend_design_tokens(
                content=content,
                allowed_hex=allowed_hex,
                rewrite_map=rewrite_map,
            )
            if token_rewrites:
                if action_type == "write_file":
                    setattr(action, "content", normalized_content)
                    content = normalized_content
                elif action_type == "apply_patch":
                    original_patch = getattr(action, "patch", None)
                    if isinstance(original_patch, str):
                        rewritten_patch = original_patch
                        for source_hex, target_hex in token_rewrites:
                            rewritten_patch = rewritten_patch.replace(source_hex, target_hex)
                            rewritten_patch = rewritten_patch.replace(source_hex.lower(), target_hex)
                            rewritten_patch = rewritten_patch.replace(source_hex.upper(), target_hex.upper())
                        setattr(action, "patch", rewritten_patch)
                        content = self._extract_added_patch_content(rewritten_patch)
            if enforce_inline and (bootstrap_mode or recovery_strategy == "design_token_auto_normalize"):
                # Bootstrap scaffolds should not fail hard for inline-style drift.
                # Strip inline style attributes before validation and continue.
                stripped = _INLINE_STYLE_ATTR_RE.sub("", content)
                if stripped != content:
                    if action_type == "write_file":
                        setattr(action, "content", stripped)
                    elif action_type == "apply_patch":
                        original_patch = getattr(action, "patch", None)
                        if isinstance(original_patch, str):
                            setattr(action, "patch", _INLINE_STYLE_ATTR_RE.sub("", original_patch))
                    content = stripped
            stripped_style_blocks = _STYLE_BLOCK_RE.sub("", content)
            if stripped_style_blocks != content:
                if action_type == "write_file":
                    setattr(action, "content", stripped_style_blocks)
                elif action_type == "apply_patch":
                    original_patch = getattr(action, "patch", None)
                    if isinstance(original_patch, str):
                        setattr(action, "patch", _STYLE_BLOCK_RE.sub("", original_patch))
                content = stripped_style_blocks
            if enforce_inline and _STYLE_ATTR_RE.search(content):
                records.append(
                    {
                        "type": "design_contract_violation",
                        "rule": "disallow_inline_styles",
                        "file": path,
                        "value": None,
                        "message": (
                            f"Design contract violation in {path}: inline style attributes are disallowed. "
                            "Use tokenized classes."
                        ),
                    }
                )
            if enforce_tokens:
                for raw_hex in _HEX_COLOR_RE.findall(content):
                    lowered = raw_hex.lower()
                    if recovery_strategy == "design_token_auto_normalize":
                        # In token-normalization recovery passes, treat first-pass color drift as
                        # auto-normalized to avoid dead loops on deterministic scaffolding.
                        allowed_hex.add(lowered)
                        continue
                    if lowered not in allowed_hex:
                        records.append(
                            {
                                "type": "design_contract_violation",
                                "rule": "enforce_color_tokens",
                                "file": path,
                                "value": raw_hex,
                                "message": (
                                    f"Design contract violation in {path}: ad-hoc hex color {raw_hex} is not in "
                                    "token_registry.colors."
                                ),
                            }
                        )
                        break
            if allowed_components:
                discovered = {
                    tag
                    for tag in _COMPONENT_TAG_RE.findall(content)
                    if isinstance(tag, str) and tag not in allowed_components
                }
                if discovered:
                    sorted_discovered = sorted(discovered)
                    records.append(
                        {
                            "type": "design_contract_violation",
                            "rule": "allowed_components",
                            "file": path,
                            "value": ",".join(sorted_discovered[:6]),
                            "message": (
                                f"Design contract violation in {path}: unauthorized components "
                                f"{', '.join(sorted_discovered[:6])}."
                            ),
                        }
                    )
        return records

    def _is_project_contract_repair_candidate(
        self,
        *,
        work_item: WorkItem,
        violations: list[str],
    ) -> bool:
        if not violations:
            return False
        if "PLAN" in work_item.type:
            return False
        if work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION", "RUN_TESTS"}:
            return False
        return True

    def _is_likely_truncated_json_output(self, raw: str, error: Exception) -> bool:
        if not isinstance(error, json.JSONDecodeError):
            return False
        if not isinstance(raw, str) or not raw.strip():
            return False
        message = str(error).lower()
        stripped = raw.rstrip()
        return (
            "unterminated string" in message
            or "unterminated" in message
            or error.pos >= max(0, len(raw) - 128)
            or stripped[-1] not in {"}", "]"}
        )

    def _parse_codex_plan(self, raw: str) -> CodexPlan:
        parse_error: Exception | None = None
        try:
            return CodexPlan.model_validate(json.loads(raw))
        except Exception as exc:
            parse_error = exc
        candidate = _extract_structured_json_candidate(raw)
        if not candidate or candidate == raw.strip():
            if parse_error is not None:
                raise parse_error
            raise ValueError("Structured output parsing failed")
        return CodexPlan.model_validate(json.loads(candidate))

    def _parse_retry_max_tokens(
        self,
        *,
        current_max_tokens: int,
        selected_model_tier: str,
        work_item: WorkItem,
        contract: ExecutionContract | None,
    ) -> int:
        if contract is not None and contract.budget.budget_mode != "NORMAL":
            return current_max_tokens

        tier_default = {
            "tier_premium": int(getattr(self.settings, "ai_default_completion_premium_tokens", 2000)),
            "tier_economy": int(getattr(self.settings, "ai_default_completion_economy_tokens", 800)),
        }.get(
            selected_model_tier,
            int(getattr(self.settings, "ai_default_completion_standard_tokens", self.settings.codex_max_tokens)),
        )
        boosted_floor = tier_default
        boosted_cap = 4000
        if work_item.type == "WRITE_TESTS":
            # WRITE_TESTS responses frequently include larger JSON payloads; give them
            # extra room to avoid truncated structured output.
            boosted_floor = max(boosted_floor, 3200 if selected_model_tier != "tier_economy" else 1600)
            boosted_cap = 6000 if selected_model_tier != "tier_economy" else 3200
        elif work_item.type in {"CODE_FRONTEND", "CODE_BACKEND", "GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING"}:
            boosted_floor = max(boosted_floor, 2200 if selected_model_tier != "tier_economy" else 1200)
            if self._frontend_retry_cap_bump_active(work_item):
                boosted_floor = max(
                    boosted_floor,
                    int(getattr(self.settings, "codex_frontend_retry_completion_boost_tokens", boosted_floor)),
                )
                boosted_cap = max(
                    boosted_cap,
                    int(getattr(self.settings, "codex_frontend_retry_completion_cap_tokens", boosted_cap)),
                )
        elif work_item.type not in {"PLAN_DAG", "PLAN_BACKEND_TOPOLOGY", "REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            boosted_floor = max(boosted_floor, 1600)
        boosted = min(max(current_max_tokens * 2, boosted_floor), boosted_cap)
        if contract is not None and contract.budget.remaining_tokens > 0:
            boosted = min(boosted, max(current_max_tokens, contract.budget.remaining_tokens))
        return max(current_max_tokens, boosted)

    def _initial_completion_token_estimate(
        self,
        *,
        base_max_tokens: int,
        selected_model_tier: str,
        work_item: WorkItem,
        contract: ExecutionContract | None,
    ) -> int:
        if work_item.type in {"PLAN_DAG", "PLAN_BACKEND_TOPOLOGY"}:
            # Keep planning responses compact and schema-focused to avoid large
            # truncated patch payloads in the planning stage.
            planning_cap = int(getattr(self.settings, "ai_default_completion_economy_tokens", 800))
            return max(300, min(base_max_tokens, planning_cap))
        if work_item.type == "WRITE_TESTS":
            return self._parse_retry_max_tokens(
                current_max_tokens=base_max_tokens,
                selected_model_tier=selected_model_tier,
                work_item=work_item,
                contract=contract,
            )
        if work_item.type == "CODE_FRONTEND" and _is_static_frontend_scope(work_item.payload):
            return self._parse_retry_max_tokens(
                current_max_tokens=base_max_tokens,
                selected_model_tier=selected_model_tier,
                work_item=work_item,
                contract=contract,
            )
        return base_max_tokens

    def _build_parse_retry_prompt(
        self,
        *,
        user_prompt: str,
        raw: str,
        error: Exception,
        work_item: WorkItem,
        allowed_files: list[str],
        retry_count: int,
    ) -> str:
        allowed_text = ", ".join(allowed_files[:6]) if allowed_files else "the scoped files"
        error_name = error.__class__.__name__
        error_text = str(error).strip() or "unknown parse error"
        raw_excerpt = (raw or "").strip()
        if len(raw_excerpt) > 1200:
            raw_excerpt = raw_excerpt[-1200:]
        issue = (
            "truncated before the JSON object finished"
            if self._is_likely_truncated_json_output(raw, error)
            else "invalid JSON or did not match the schema"
        )
        guidance = [
            f"Your previous output was {issue}. Re-emit the full response from scratch.",
            f"Parser error: {error_name}: {error_text}",
            "Respond with EXACTLY one complete JSON object matching the schema.",
            "Do not include markdown fences, explanations, or any prose outside the JSON object.",
            "Do not omit closing quotes, braces, or brackets.",
            "Do not reconsider the broader feature plan; repair the existing bounded plan only.",
            f"Stay within these files: {allowed_text}.",
        ]
        if raw_excerpt:
            guidance.append("Previous raw output excerpt (for debugging; do not copy verbatim if malformed):")
            guidance.append(raw_excerpt)
        primary_scope = _target_files_from_payload(work_item.payload) or allowed_files[:1]
        if primary_scope:
            guidance.append(f"Prefer touching only this primary file unless the schema requires otherwise: {', '.join(primary_scope[:2])}.")
        if _is_backend_codegen_type(work_item.type) or work_item.type == "WRITE_TESTS":
            guidance.append(
                "If a long apply_patch diff risks truncation, prefer write_file for a single targeted file or a shorter patch."
            )
        if work_item.type == "CODE_FRONTEND":
            recovery_strategy = str((work_item.payload or {}).get("recovery_strategy") or "").strip().lower()
            if recovery_strategy == "componentization_repair":
                guidance.append(
                    "Recovery override: structural contract violation was detected."
                    " Extract oversized root-page sections into components and keep the root page as a thin composition shell."
                )
                guidance.append(
                    "Prefer creating governed components such as HeroSection, LeadCaptureForm, PricingSection, and CTASection when relevant."
                )
            elif recovery_strategy == "write_file_preferred":
                guidance.append(
                    "Recovery override: the previous patch failed to apply."
                    " For this retry, prefer write_file for the primary scoped file with complete updated contents."
                )
                guidance.append(
                    "Do not embed data: URIs, minified script blobs, or base64 payloads inside HTML."
                    " Keep scripts in concise source form only."
                )
            else:
                guidance.append(
                    "If output size is large, avoid full-file write_file rewrites; emit minimal apply_patch hunks to keep JSON compact."
                )
        if _is_backend_codegen_type(work_item.type):
            recovery_strategy = str((work_item.payload or {}).get("recovery_strategy") or "").strip().lower()
            if recovery_strategy == "write_file_preferred":
                guidance.append(
                    "Recovery override: emit write_file for scoped backend file updates."
                    " Do not emit apply_patch for this retry."
                )
        if work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            guidance.append(
                "This is a review stage. Return only note actions with concise findings or approval guidance."
            )
            guidance.append(
                "Never emit apply_patch, write_file, or delete_file actions, and do not reproduce the diff or file contents."
            )
        if work_item.type == "CODE_FRONTEND" and _is_static_frontend_scope(work_item.payload):
            recovery_strategy = str((work_item.payload or {}).get("recovery_strategy") or "").strip().lower()
            if recovery_strategy == "write_file_preferred":
                guidance.append(
                    "For this bounded static frontend recovery attempt, use write_file for index.html when in scope."
                )
                guidance.append(
                    "Keep the write concise and deterministic. Do not add external helper files, data: URLs, or inline encoded script payloads."
                )
            else:
                guidance.append(
                    "For a bounded static frontend file, prefer minimal apply_patch edits. Use write_file only for new files or tiny rewrites."
                )
        if work_item.type == "WRITE_TESTS":
            guidance.append(
                "For WRITE_TESTS, prefer write_file with full updated contents for scoped test files when patch offsets may have drifted; use apply_patch only for small, stable hunks."
            )
            guidance.append(
                "Do not leave conflicting old-behavior and new-behavior assertions in the same suite; reconcile stale tests to the current task goal."
            )
        if self._strict_output_contract_mode(work_item):
            guidance.append("Strict recovery mode is active after prior structured-output failures.")
            guidance.append("Keep output deterministic and compact: emit one schema-valid JSON object with minimal fields.")
            guidance.append("Avoid optional commentary or extra note actions unless required for execution.")
        guidance.append(f"This is structured output retry {retry_count}.")
        return f"{user_prompt}\n\n" + "\n".join(guidance)

    async def _repair_plan_after_patch_failure(
        self,
        *,
        client: OpenAIClient,
        prepared,
        user_prompt: str,
        allowed_files: list[str],
        error_message: str,
        work_item: WorkItem,
        contract: ExecutionContract | None,
    ) -> tuple[CodexPlan, str, dict[str, Any], str, str]:
        allowed_text = ", ".join(allowed_files[:6]) if allowed_files else "the planned file scope"
        lowered_error = (error_message or "").lower()
        static_frontend_scope = work_item.type == "CODE_FRONTEND" and _is_static_frontend_scope(
            work_item.payload if isinstance(work_item.payload, dict) else {}
        )
        patch_drift_error = any(
            marker in lowered_error
            for marker in (
                "patch does not apply",
                "patch check failed",
                "corrupt patch",
                "error: patch failed:",
                "patch fragment without header",
            )
        )
        repair_prompt = (
            f"{user_prompt}\n\n"
            "The previous action plan failed while applying a generated patch.\n"
            f"Failure: {error_message}\n"
            "Do not redesign the solution or broaden the run plan; repair the existing scoped change only.\n"
            f"Stay within these files: {allowed_text}.\n"
            "Return a new JSON object matching the schema.\n"
            "If you use apply_patch, include full file headers such as --- a/path and +++ b/path before each hunk.\n"
            "If you use apply_patch, every hunk header must use exact unified diff line numbers like @@ -10,2 +10,6 @@.\n"
            "Do not use placeholder hunk headers such as @@ ... @@.\n"
            "Do not return hunk-only patch fragments that start with @@ before file headers.\n"
            "For single-file HTML/CSS/JS edits, prefer minimal apply_patch hunks that touch only required lines.\n"
            "Do not include prose outside the JSON object."
        )
        if work_item.type == "WRITE_TESTS":
            repair_prompt += (
                "\nFor WRITE_TESTS after a patch-apply failure, do not emit apply_patch."
                " Emit write_file actions with full updated contents for scoped Python test files."
                " Keep edits minimal and behavior-oriented."
                " Never modify non-test files such as index.html."
            )
        if work_item.type == "CODE_FRONTEND":
            recovery_strategy = str((work_item.payload or {}).get("recovery_strategy") or "").strip().lower()
            if recovery_strategy == "componentization_repair":
                repair_prompt += (
                    "\nFor this CODE_FRONTEND recovery retry, perform componentization repair."
                    " Move large root-page sections into reusable component files and reduce the root page to composition."
                    " Keep edits constrained to allowed files and avoid monolithic index/root rewrites."
                )
            elif recovery_strategy == "write_file_preferred" or (static_frontend_scope and patch_drift_error):
                repair_prompt += (
                    "\nFor this CODE_FRONTEND recovery retry, avoid apply_patch."
                    " Emit write_file for the primary scoped file (index.html when present) with complete updated content."
                    " Keep scope bounded to allowed files."
                    " Do not embed data: URLs, base64 blobs, or encoded inline scripts."
                )
        if _is_backend_codegen_type(work_item.type):
            recovery_strategy = str((work_item.payload or {}).get("recovery_strategy") or "").strip().lower()
            if recovery_strategy == "write_file_preferred":
                repair_prompt += (
                    f"\nFor this {work_item.type} recovery retry, avoid apply_patch."
                    " Emit write_file for the primary scoped backend file with complete updated content."
                    " Keep scope bounded to allowed files."
                )
        current_prompt = repair_prompt
        current_max_tokens = self.settings.codex_max_tokens
        raw = ""
        usage: dict[str, Any] = {}
        retry_reason = "patch_apply_error"
        effective_model_tier = prepared.policy.selected_model_tier
        effective_model_name = prepared.model_name or self.settings.codex_model
        system_prompt = self._system_prompt_for(work_item)
        repair_retry_limit = REPAIR_STRUCTURED_OUTPUT_RETRY_LIMIT + (
            1 if (static_frontend_scope and patch_drift_error) else 0
        )
        for retry_count in range(repair_retry_limit + 1):
            effective_model_tier = self._effective_model_tier(
                policy=prepared.policy,
                work_item=work_item,
                attempt=retry_count + 1,
                retry_reason=retry_reason,
            )
            effective_model_name = self._model_name_for_tier(
                effective_model_tier,
                fallback=prepared.model_name or self.settings.codex_model,
            )
            raw, usage = await client.generate(
                system_prompt,
                current_prompt,
                model=effective_model_name,
                temperature=0.0 if retry_count > 0 else self.settings.codex_temperature,
                max_tokens=current_max_tokens,
                timeout=self.settings.codex_timeout_seconds,
            )
            try:
                plan = self._parse_codex_plan(raw)
                break
            except Exception as exc:
                parse_failure = isinstance(exc, json.JSONDecodeError) or "validation" in exc.__class__.__name__.lower()
                if parse_failure and retry_count < repair_retry_limit:
                    await self._job_manager.record_retry(prepared.job_id, "structured_parser_failure")
                    retry_reason = "structured_parser_failure"
                    if work_item.type == "CODE_FRONTEND" and static_frontend_scope and patch_drift_error:
                        if isinstance(work_item.payload, dict):
                            work_item.payload["recovery_strategy"] = "write_file_preferred"
                            work_item.payload["prior_patch_failures"] = int(work_item.payload.get("prior_patch_failures") or 0) + 1
                        # Hard guard: on malformed repair output in drift recovery, force deterministic write mode.
                        current_prompt = (
                            f"{repair_prompt}\n\n"
                            "Repair output parsing failed. Switch immediately to deterministic write mode.\n"
                            "Return JSON only. Emit write_file actions for the primary scoped frontend file with complete updated content.\n"
                            "Do not emit apply_patch in this retry.\n"
                        )
                    else:
                        current_prompt = self._build_parse_retry_prompt(
                            user_prompt=repair_prompt,
                            raw=raw,
                            error=exc,
                            work_item=work_item,
                            allowed_files=allowed_files,
                            retry_count=retry_count + 1,
                        )
                    next_retry_tier = self._effective_model_tier(
                        policy=prepared.policy,
                        work_item=work_item,
                        attempt=retry_count + 2,
                        retry_reason=retry_reason,
                    )
                    current_max_tokens = self._parse_retry_max_tokens(
                        current_max_tokens=current_max_tokens,
                        selected_model_tier=next_retry_tier,
                        work_item=work_item,
                        contract=contract,
                    )
                    continue
                raise ValueError(f"Patch repair output was invalid: {exc}") from exc
        log.warning(
            "AI patch repair retry run_id=%s work_item_id=%s ai_job_id=%s work_item_type=%s",
            work_item.run_id,
            work_item.id,
            prepared.job_id,
            work_item.type,
        )
        return plan, raw, usage, effective_model_tier, effective_model_name

    async def _repair_plan_after_stage_scope_violation(
        self,
        *,
        client: OpenAIClient,
        prepared,
        user_prompt: str,
        allowed_files: list[str],
        violations: list[str],
        work_item: WorkItem,
        contract: ExecutionContract | None,
    ) -> tuple[CodexPlan, str, dict[str, Any], str, str]:
        allowed_text = ", ".join(allowed_files[:6]) if allowed_files else "the scoped files"
        repair_prompt = (
            f"{user_prompt}\n\n"
            "The previous action plan violated the stage scope.\n"
            f"Violations: {'; '.join(violations)}\n"
            "Do not redesign the solution or broaden the run plan; repair the existing scoped change only.\n"
            f"Stay within these files: {allowed_text}.\n"
            "Return a new JSON object matching the schema.\n"
            "Do not include prose outside the JSON object."
        )
        if "PLAN" in work_item.type:
            repair_prompt += (
                "\nThis is a planning stage. Return only note actions that describe the intended patch, tests, "
                "and validation sequence. Never emit apply_patch, write_file, or delete_file actions."
            )
        elif work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            repair_prompt += (
                "\nThis is a review stage. Return only note actions with concise findings or approval guidance. "
                "Never emit apply_patch, write_file, or delete_file actions."
            )
        elif work_item.type == "WRITE_TESTS":
            payload = work_item.payload if isinstance(work_item.payload, dict) else {}
            package_affinity = str(payload.get("package_affinity") or "").strip().lower()
            if package_affinity.startswith("apps/web"):
                repair_prompt += (
                    "\nWRITE_TESTS(frontend) must generate framework-native Vue/Vite tests."
                    " Modify only scoped JS/TS spec files (for example *.spec.ts) under apps/web."
                    " Use Vitest + Vue Test Utils conventions, no Python tests, and never modify implementation files in this repair."
                )
            else:
                repair_prompt += (
                    "\nWRITE_TESTS may only modify Python test files whose basename starts with test_. "
                    "Touch only scoped test files and prefer write_file with the full updated test contents."
                    " Never modify non-test files such as index.html."
                )
        current_prompt = repair_prompt
        current_max_tokens = self.settings.codex_max_tokens
        raw = ""
        usage: dict[str, Any] = {}
        retry_reason = "stage_scope_violation"
        effective_model_tier = prepared.policy.selected_model_tier
        effective_model_name = prepared.model_name or self.settings.codex_model
        system_prompt = self._system_prompt_for(work_item)
        for retry_count in range(REPAIR_STRUCTURED_OUTPUT_RETRY_LIMIT + 1):
            effective_model_tier = self._effective_model_tier(
                policy=prepared.policy,
                work_item=work_item,
                attempt=retry_count + 1,
                retry_reason=retry_reason,
            )
            effective_model_name = self._model_name_for_tier(
                effective_model_tier,
                fallback=prepared.model_name or self.settings.codex_model,
            )
            raw, usage = await client.generate(
                system_prompt,
                current_prompt,
                model=effective_model_name,
                temperature=self.settings.codex_temperature,
                max_tokens=current_max_tokens,
                timeout=self.settings.codex_timeout_seconds,
            )
            try:
                plan = self._parse_codex_plan(raw)
                break
            except Exception as exc:
                parse_failure = isinstance(exc, json.JSONDecodeError) or "validation" in exc.__class__.__name__.lower()
                if parse_failure and retry_count < REPAIR_STRUCTURED_OUTPUT_RETRY_LIMIT:
                    await self._job_manager.record_retry(prepared.job_id, "structured_parser_failure")
                    retry_reason = "structured_parser_failure"
                    next_retry_tier = self._effective_model_tier(
                        policy=prepared.policy,
                        work_item=work_item,
                        attempt=retry_count + 2,
                        retry_reason=retry_reason,
                    )
                    current_max_tokens = self._parse_retry_max_tokens(
                        current_max_tokens=current_max_tokens,
                        selected_model_tier=next_retry_tier,
                        work_item=work_item,
                        contract=contract,
                    )
                    current_prompt = self._build_parse_retry_prompt(
                        user_prompt=repair_prompt,
                        raw=raw,
                        error=exc,
                        work_item=work_item,
                        allowed_files=allowed_files,
                        retry_count=retry_count + 1,
                    )
                    continue
                raise ValueError(f"Stage-scope repair output was invalid: {exc}") from exc
        log.warning(
            "AI stage-scope repair retry run_id=%s work_item_id=%s ai_job_id=%s work_item_type=%s",
            work_item.run_id,
            work_item.id,
            prepared.job_id,
            work_item.type,
        )
        return plan, raw, usage, effective_model_tier, effective_model_name

    async def _repair_plan_after_project_contract_violation(
        self,
        *,
        client: OpenAIClient,
        prepared,
        user_prompt: str,
        allowed_files: list[str],
        violations: list[str],
        work_item: WorkItem,
        contract: ExecutionContract | None,
        enforcement_mode: str,
    ) -> tuple[CodexPlan, str, dict[str, Any], str, str]:
        allowed_text = ", ".join(allowed_files[:6]) if allowed_files else "the scoped files"
        repair_prompt = (
            f"{user_prompt}\n\n"
            "Your previous response violated the project contract.\n"
            f"Violations: {'; '.join(violations)}\n"
            "Do not redesign the feature or broaden the run plan. Repair only the scoped change.\n"
            f"Stay within these files: {allowed_text}.\n"
            "Replace inline styles with classes/tokens and replace ad-hoc hex colors with approved tokenized styles.\n"
            "Return a corrected JSON object matching the schema.\n"
            "Do not include prose outside the JSON object."
        )
        if work_item.type in {"CODE_FRONTEND", "CODE_BACKEND", "GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING"}:
            repair_prompt += (
                "\nIf a long apply_patch diff risks malformed hunks, prefer write_file for one scoped file with full contents."
            )
        if work_item.type == "WRITE_TESTS":
            payload = work_item.payload if isinstance(work_item.payload, dict) else {}
            package_affinity = str(payload.get("package_affinity") or "").strip().lower()
            if package_affinity.startswith("apps/web"):
                repair_prompt += (
                    "\nWRITE_TESTS(frontend): regenerate scoped frontend tests using Vitest + Vue Test Utils."
                    " Use JS/TS spec files under apps/web and never emit Python test modules."
                    " Never modify non-test implementation files."
                )
            else:
                repair_prompt += (
                    "\nWRITE_TESTS may only modify scoped test files. Never modify non-test implementation files."
                )
        if enforcement_mode == "strict":
            repair_prompt += "\nStrict enforcement is active. Any contract violation will be rejected."
        else:
            repair_prompt += "\nWarn enforcement is active. Violations are logged, but you should still correct them now."

        current_prompt = repair_prompt
        current_max_tokens = self.settings.codex_max_tokens
        raw = ""
        usage: dict[str, Any] = {}
        retry_reason = "project_contract_violation"
        effective_model_tier = prepared.policy.selected_model_tier
        effective_model_name = prepared.model_name or self.settings.codex_model
        system_prompt = self._system_prompt_for(work_item)
        for retry_count in range(REPAIR_STRUCTURED_OUTPUT_RETRY_LIMIT + 1):
            effective_model_tier = self._effective_model_tier(
                policy=prepared.policy,
                work_item=work_item,
                attempt=retry_count + 1,
                retry_reason=retry_reason,
            )
            effective_model_name = self._model_name_for_tier(
                effective_model_tier,
                fallback=prepared.model_name or self.settings.codex_model,
            )
            raw, usage = await client.generate(
                system_prompt,
                current_prompt,
                model=effective_model_name,
                temperature=self.settings.codex_temperature,
                max_tokens=current_max_tokens,
                timeout=self.settings.codex_timeout_seconds,
            )
            try:
                plan = self._parse_codex_plan(raw)
                break
            except Exception as exc:
                parse_failure = isinstance(exc, json.JSONDecodeError) or "validation" in exc.__class__.__name__.lower()
                if parse_failure and retry_count < REPAIR_STRUCTURED_OUTPUT_RETRY_LIMIT:
                    await self._job_manager.record_retry(prepared.job_id, "structured_parser_failure")
                    retry_reason = "structured_parser_failure"
                    next_retry_tier = self._effective_model_tier(
                        policy=prepared.policy,
                        work_item=work_item,
                        attempt=retry_count + 2,
                        retry_reason=retry_reason,
                    )
                    current_max_tokens = self._parse_retry_max_tokens(
                        current_max_tokens=current_max_tokens,
                        selected_model_tier=next_retry_tier,
                        work_item=work_item,
                        contract=contract,
                    )
                    current_prompt = self._build_parse_retry_prompt(
                        user_prompt=repair_prompt,
                        raw=raw,
                        error=exc,
                        work_item=work_item,
                        allowed_files=allowed_files,
                        retry_count=retry_count + 1,
                    )
                    continue
                raise ValueError(f"Project-contract repair output was invalid: {exc}") from exc
        log.warning(
            "AI project-contract repair retry run_id=%s work_item_id=%s ai_job_id=%s work_item_type=%s mode=%s",
            work_item.run_id,
            work_item.id,
            prepared.job_id,
            work_item.type,
            enforcement_mode,
        )
        return plan, raw, usage, effective_model_tier, effective_model_name

    async def _record_execution_budget(
        self,
        context: RunContext,
        *,
        prepared_job_id: str,
        work_item_id: str,
        selected_model_tier: str,
        input_tokens: int,
        output_tokens: int,
    ) -> ExecutionContract | None:
        try:
            async with SessionLocal() as session:
                run = await session.get(Run, context.run_id)
                if run is None:
                    return context.execution_contract
                contract = await record_run_budget_usage(
                    session,
                    run,
                    work_item_id=work_item_id,
                    ai_job_id=prepared_job_id,
                    selected_model_tier=selected_model_tier,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                await session.commit()
                context.execution_contract = contract
                return contract
        except Exception:
            return context.execution_contract

    def _instructions_for(self, work_item: WorkItem, context: RunContext | None = None) -> str:
        payload = work_item.payload or {}
        recovery_strategy = str(payload.get("recovery_strategy") or "").strip().lower()
        mutation_strategy = str(payload.get("mutation_strategy") or "").strip().lower()
        contract = context.execution_contract if context is not None else None
        target_files = (
            list(contract.target_files)
            if contract is not None and contract.target_files
            else _target_files_from_payload(payload)
        )
        edit_budget = (
            {
                "mode": contract.scope_mode,
                "file_budget": contract.file_budget,
                "hard_file_budget": contract.hard_file_budget,
            }
            if contract is not None
            else _edit_budget_from_payload(payload)
        )
        static_frontend_scope = _is_static_frontend_scope(payload) or (
            bool(target_files)
            and all(Path(path).suffix.lower() in {".html", ".css", ".js", ".mjs", ".cjs"} for path in target_files)
        )
        architecture = context.architecture_profile if context and isinstance(context.architecture_profile, dict) else {}
        project_contract = context.project_contract if context and isinstance(context.project_contract, dict) else {}
        review_stage = work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}
        if review_stage:
            base = (
                "Produce JSON per schema. This is a review task. "
                "Return only note actions with concise findings, approval guidance, risks, or follow-up recommendations. "
                "Do not mutate repository files. Never emit apply_patch, write_file, or delete_file actions. "
                "Do not restate the full diff or copy large file contents into the response."
            )
        else:
            base = (
                "Produce JSON per schema. Prefer apply_patch with unified diff. "
                "Use write_file for new files or complete replacements. Keep changes minimal. "
                "If you use apply_patch, include full file headers such as --- a/path and +++ b/path before each hunk. "
                "If you use apply_patch, emit exact unified diff hunk headers with numeric line ranges, "
                "never use placeholder headers such as @@ ... @@, and never return a hunk-only fragment before file headers."
            )
        if target_files:
            file_list = ", ".join(target_files[:4])
            base += (
                f" Restrict edits to these files unless validation proves a neighboring file is required: {file_list}. "
                f"Keep the patch within {edit_budget['file_budget']} files and prefer a {edit_budget['mode']} strategy."
            )
        mutation_class = str(payload.get("mutation_class") or "").strip().upper()
        allowed_operations = [str(item).strip() for item in (payload.get("allowed_operations") or []) if isinstance(item, str) and str(item).strip()]
        forbidden_operations = [str(item).strip() for item in (payload.get("forbidden_operations") or []) if isinstance(item, str) and str(item).strip()]
        protected_files = [str(item).strip() for item in (payload.get("protected_files") or []) if isinstance(item, str) and str(item).strip()]
        allowed_zones = [str(item).strip() for item in (payload.get("allowed_zones") or []) if isinstance(item, str) and str(item).strip()]
        forbidden_zones = [str(item).strip() for item in (payload.get("forbidden_zones") or []) if isinstance(item, str) and str(item).strip()]
        if mutation_class:
            base += f" Mutation authority class: {mutation_class}."
        if allowed_operations:
            base += " Allowed operations: " + ", ".join(allowed_operations[:6]) + "."
        if forbidden_operations:
            base += " Forbidden operations: " + ", ".join(forbidden_operations[:6]) + "."
        if protected_files:
            base += " Protected infrastructure files (do not replace outside FOUNDATION): " + ", ".join(protected_files[:4]) + "."
        if allowed_zones:
            base += " Allowed zones: " + ", ".join(allowed_zones[:6]) + "."
        if forbidden_zones:
            base += " Forbidden zones: " + ", ".join(forbidden_zones[:6]) + "."
        if bool(payload.get("zone_composer_required")):
            base += " For LandingPage.vue, edit only inside explicit zone markers <!-- zone:<name>:start --> ... <!-- zone:<name>:end -->."
        if mutation_strategy in MUTATION_STRATEGIES:
            base += f" Mutation strategy: {mutation_strategy}."
            if mutation_strategy == "write_file":
                base += " Prefer write_file for scoped deterministic updates; avoid apply_patch unless absolutely required."
            elif mutation_strategy == "apply_patch":
                base += " Prefer apply_patch for minimal surgical changes."
        protected_paths = (
            list(contract.protected_paths)
            if contract is not None
            else architecture.get("protected_paths", []) if isinstance(architecture.get("protected_paths"), list) else []
        )
        safe_paths = (
            list(contract.safe_paths)
            if contract is not None
            else architecture.get("safe_paths", []) if isinstance(architecture.get("safe_paths"), list) else []
        )
        assumptions = list(contract.assumptions_used) if contract is not None else []
        if assumptions:
            base += " Architecture assumptions: " + "; ".join(str(item) for item in assumptions[:4]) + "."
        if protected_paths:
            base += (
                " Avoid protected zones unless the task explicitly requires them: "
                + ", ".join(str(path) for path in protected_paths[:4])
                + "."
            )
        if safe_paths:
            base += " Prefer safe refactor zones when possible: " + ", ".join(str(path) for path in safe_paths[:4]) + "."
        recipe_names = list(contract.validation_recipes) if contract is not None else []
        if recipe_names:
            base += " Validation recipes available: " + ", ".join(recipe_names[:4]) + "."
        project_summary = project_contract.get("summary") if isinstance(project_contract.get("summary"), dict) else {}
        project_enforcement = (
            project_contract.get("enforcement") if isinstance(project_contract.get("enforcement"), dict) else {}
        )
        project_enforcement_mode = _project_contract_enforcement_mode(project_contract)
        brand_kit = project_contract.get("brand_kit") if isinstance(project_contract.get("brand_kit"), dict) else {}
        design_system = (
            project_contract.get("design_system") if isinstance(project_contract.get("design_system"), dict) else {}
        )
        design_packet = _design_context_packet(project_contract) if project_contract else {}
        if isinstance(project_summary, dict):
            active_rules = [
                item
                for item in project_summary.get("active_rules", [])
                if isinstance(item, str) and item.strip()
            ]
            if active_rules:
                base += " Project contract rules: " + ", ".join(active_rules[:4]) + "."
        if design_packet:
            base += (
                " DESIGN_CONTEXT_PACKET: "
                + json.dumps(
                    {
                        "experience_blueprint": design_packet.get("experience_blueprint"),
                        "visual_tone": design_packet.get("visual_tone"),
                        "layout_density": design_packet.get("layout_density"),
                        "allowed_components": design_packet.get("allowed_components", [])[:8],
                    },
                    sort_keys=True,
                )
                + "."
            )
            base += " Frontend generation must obey this packet and compose from governed primitives only."
            if work_item.type == "CODE_FRONTEND":
                variant = str((work_item.payload or {}).get("component_variant") or design_packet.get("experience_blueprint") or "premium_saas")
                capability_packet = build_component_capability_packet(
                    allowed_components=list(design_packet.get("allowed_components", []) or []),
                    variant=variant,
                )
                if capability_packet.get("components"):
                    base += " COMPONENT_CAPABILITY_PACKET: " + json.dumps(capability_packet, sort_keys=True) + "."
                    base += " Assemble UI from this capability packet; do not invent large inline sections."
        brand_tokens = brand_kit.get("tokens") if isinstance(brand_kit.get("tokens"), dict) else {}
        token_names: list[str] = []
        if brand_tokens:
            token_names = [str(name).strip() for name in list(brand_tokens.keys())[:6] if str(name).strip()]
            if token_names:
                base += " Use brand tokens when styling UI changes: " + ", ".join(token_names) + "."
        components_value = design_system.get("components")
        components: list[str] = []
        if isinstance(components_value, list):
            for item in components_value:
                if isinstance(item, str) and item.strip():
                    components.append(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        components.append(name.strip())
            if components:
                base += " Prefer approved design-system components: " + ", ".join(components[:6]) + "."
        if project_enforcement_mode in {"warn", "strict"} and not review_stage:
            base += (
                f" Project contract enforcement mode: {project_enforcement_mode.upper()}. "
                "You MUST follow project contract rules for this task."
            )
            if bool(project_enforcement.get("disallow_inline_styles")):
                base += " Do NOT use inline style attributes."
            if bool(project_enforcement.get("enforce_color_tokens")):
                base += " Do NOT introduce raw hex colors outside approved tokens."
                allowed_hex_values = sorted(
                    _flatten_token_colors(
                        design_packet.get("token_registry")
                        if isinstance(design_packet.get("token_registry"), dict)
                        else {}
                    )
                )
                if allowed_hex_values:
                    base += (
                        " If a hex literal is absolutely unavoidable, use only approved values: "
                        + ", ".join(allowed_hex_values[:12])
                        + "."
                    )
            if components:
                base += " Use approved components when relevant: " + ", ".join(components[:6]) + "."
            if token_names:
                base += " Use approved brand tokens: " + ", ".join(token_names[:6]) + "."
            if project_enforcement_mode == "strict":
                base += " Violation of these rules will cause rejection."
            else:
                base += " Violations are logged and trigger corrective retries; return a contract-compliant patch."
        if bool(project_enforcement.get("disallow_inline_styles")):
            base += " Avoid inline style attributes; prefer tokenized classes or shared styles."
        if bool(project_enforcement.get("enforce_color_tokens")):
            base += " Avoid introducing ad-hoc hex colors outside the brand token palette."
        if contract is not None and contract.validation_state not in {"", "NOT_REQUIRED"}:
            base += f" Current validation state: {contract.validation_state}."
        if contract is not None and contract.retry_state not in {"", "IDLE"}:
            base += f" Current retry state: {contract.retry_state}."
        if static_frontend_scope and not review_stage:
            base += (
                " This is a static frontend task. Keep implementation inside the scoped HTML/CSS/JS files and "
                "do not introduce Python helper modules or backend files unless the task explicitly asks for them. "
                "For single-file HTML/CSS/JS edits, prefer minimal apply_patch hunks; use write_file only when a tiny full-file rewrite is truly necessary."
            )
        if work_item.type == "CODE_FRONTEND" and static_frontend_scope:
            base += (
                " For a bounded static frontend file, prefer tightly scoped apply_patch edits and avoid full-file rewrites unless absolutely necessary."
            )
            topology_plan = (
                (work_item.payload or {}).get("frontend_topology_plan")
                if isinstance(work_item.payload, dict)
                else None
            )
            if isinstance(topology_plan, dict):
                sections = topology_plan.get("sections") if isinstance(topology_plan.get("sections"), list) else []
                component_files = (
                    topology_plan.get("component_files")
                    if isinstance(topology_plan.get("component_files"), list)
                    else []
                )
                root_file = str(topology_plan.get("root_file") or "index.html")
                if sections or component_files:
                    base += (
                        " Frontend topology plan is active."
                        f" Root composition file: {root_file}."
                        f" Planned sections: {', '.join([str(s) for s in sections[:8]])}."
                        f" Planned component files: {', '.join([str(p) for p in component_files[:8]])}."
                        " Keep root file composition-oriented and place section implementation in planned component files."
                )
            if recovery_strategy == "write_file_preferred":
                base += (
                    " Recovery override: previous patch application drifted."
                    " For this retry, prefer write_file with full contents for the primary scoped file (typically index.html),"
                    " then keep any remaining edits minimal."
                )
        if work_item.type in {"CODE_FRONTEND", "GENESIS_FOUNDATION"} and not review_stage:
            base += (
                " Emit exactly one mutating action type per response: either all write_file or all apply_patch, never both."
                " Do not create or modify root-level frontend files such as LandingPage.vue/App.vue outside package roots."
                " Keep Vue page/component edits under package source roots (for monorepo typically apps/web/src/pages or apps/web/src/components)."
            )
            base += (
                " Frontend mutation contract: this repository is a governed Vue 3 + Vite + Tailwind system."
                " Pages compose sections; sections compose governed components."
                " Use Tailwind utility classes and tokenized classes only."
                " Forbidden patterns: style=, <style> blocks, raw hex colors, rgb(, and ad-hoc spacing literals."
            )
            base += (
                " Composition governance v1: every section must include a responsive container, max-width wrapper,"
                " spacing rhythm, typography hierarchy, mobile-safe layout, and overflow protection."
                " Prefer governed primitives: PageShell, SectionContainer, ContentGrid, ResponsiveStack, TestimonialCard."
                " Require max-w-*, mx-auto, responsive breakpoints, and bounded SVG/icon sizing classes."
                " Disallow unbounded giant dimensions and ad-hoc oversized layout utilities."
            )
            if _runtime_governance_mode(payload) == "stability":
                base += (
                    " Stability mode rendering policy: prioritize (1) visible rendering, (2) responsive layout,"
                    " (3) stable composition, (4) primitive reuse, (5) abstraction purity."
                    " Never sacrifice visible rendering for abstraction governance."
                    " Use self-contained Tailwind implementation by default."
                    " Only auto-compose primitives when maturity is verified_visual or production_ready."
                    " Primitive maturity states: experimental, stable, verified_visual, production_ready."
                )
            if target_files:
                canonical_frontend_targets = [
                    path for path in target_files
                    if path.startswith("apps/web/src/") or path.startswith("apps/web/index.html")
                ]
                if canonical_frontend_targets:
                    base += (
                        " Canonical frontend target paths for this task: "
                        + ", ".join(canonical_frontend_targets[:6])
                        + "."
                    )
            goal_text = " ".join(
                [
                    str(payload.get("task_title") or ""),
                    str(payload.get("goal") or ""),
                    str(payload.get("task_description") or ""),
                ]
            ).lower()
            if any(token in goal_text for token in ("testimonial", "pricing", "cta", "hero", "section")):
                base += (
                    " Topology-constrained component repair is active."
                    " Mutate only the target component file, the composition shell, and immediate governed neighbors."
                    " Never mutate index.html, App.vue, or unrelated components for this task."
                )
            if "testimonial" in goal_text:
                base += (
                    " Placeholder replacement rule: replace <TestimonialsPlaceholder /> in LandingPage composition"
                    " with the generated testimonials section component instead of creating isolated pages."
                )
            base += (
                " Composition zones are authoritative: HeroZone, FeatureZone, TestimonialsZone, CTAZone."
                " Feature tasks must mutate inside these zones and preserve the remaining zone graph."
                " Do not create standalone replacement pages for feature work."
            )
        if work_item.type == "GENESIS_FOUNDATION" and not review_stage:
            base += (
                " Genesis foundation stage: build a production-grade frontend shell before feature tasks."
                " Generate Navbar, Footer, PageShell, SectionContainer, responsive layout primitives, typography hierarchy,"
                " theme-token-ready classes, and LandingPage skeleton."
                " LandingPage must initially compose: HeroZone, FeatureZone, TestimonialsZone, CTAZone, Footer."
                " Ensure mobile-safe structure and overflow safety."
            )
            prior_failures: list[str] = []
            last_error = str(getattr(work_item, "last_error", "") or "").strip()
            if last_error:
                prior_failures.append(last_error)
            recovery_reason = str(payload.get("recovery_reason") or "").strip()
            if recovery_reason:
                prior_failures.append(f"recovery_reason={recovery_reason}")
            if prior_failures:
                base += " Previous attempt failed because: " + "; ".join(prior_failures[:2]) + "."
                base += (
                    " Do not repeat prior violations."
                    " Specifically avoid: style=, <style>, #fff, #000, rgb(."
                )
        if _is_backend_codegen_type(work_item.type):
            backend_topology_plan = (
                (work_item.payload or {}).get("backend_topology_plan")
                if isinstance(work_item.payload, dict)
                else None
            )
            if isinstance(backend_topology_plan, dict):
                module_files = (
                    backend_topology_plan.get("module_files")
                    if isinstance(backend_topology_plan.get("module_files"), dict)
                    else {}
                )
                base += (
                    " Backend topology plan is active."
                    f" Entrypoint: {backend_topology_plan.get('entrypoint_file') or 'app.py'}."
                    f" Planned modules: {', '.join([str(v) for v in list(module_files.values())[:6]])}."
                    " Keep root backend file thin and move route/business/data logic into planned modules."
                )
        test_dependency_guard = (
            " Tests must rely on the Python standard library or dependencies that are already declared in repo "
            "metadata such as requirements.txt, pyproject.toml, or package.json. Do not introduce new third-party "
            "imports such as BeautifulSoup or bs4 unless you also update the declared dependencies and the runtime "
            "is known to install them. For HTML validation, prefer html.parser or simple string assertions."
        )
        if work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"}:
            fix_prompt = (
                base
                + " You are fixing failing tests. Use the failing stack info and previous diff. "
                  "Make the smallest possible patch that addresses the failure; avoid broad refactors. "
                  "Prefer patching implementation files over test files. Treat test files as read-only verification "
                  "context unless the failure is clearly caused by a syntax, import, harness defect, or contradictory assertions in the test file itself. "
                  "If assertions depend on stale implementation details (for example exact class names/selectors/DOM nesting) and the requested behavior is already satisfied, update the scoped tests to verify behavior instead of forcing obsolete markup. "
                  "If two assertions are mutually exclusive for the current task goal, reconcile the scoped test definitions instead of oscillating implementation-only patches. "
                  "Do not weaken or rewrite assertions just to make the suite pass."
                + test_dependency_guard
            )
            target_files = _target_files_from_payload(work_item.payload if isinstance(work_item.payload, dict) else {})
            if work_item.type in {"FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_VISUAL_QUALITY"}:
                fix_prompt = (
                    base
                    + " You are fixing frontend layout composition governance violations. "
                      "Preserve existing feature topology and section reachability while repairing layout quality. "
                      "Do not rewrite page ownership layers; make the smallest bounded patch. "
                      "Use governed primitives and Tailwind-safe composition patterns."
                )
            if static_frontend_scope or "index.html" in target_files:
                fix_prompt += (
                    " For static frontend recovery, target index.html first when it is in scope. "
                    "Edit a test file only when validation proves the assertion is stale or contradictory."
                )
            return fix_prompt
        if work_item.type == "WRITE_TESTS":
            payload = work_item.payload if isinstance(work_item.payload, dict) else {}
            package_affinity = str(payload.get("package_affinity") or "").strip().lower()
            if package_affinity.startswith("apps/web"):
                return (
                    base
                    + " Framework-native test contract: this is a Vue/Vite frontend package."
                      " Generate Vitest + Vue Test Utils tests in TypeScript (*.spec.ts) colocated under apps/web (prefer component-local tests directories)."
                      " Never generate Python test files for frontend Vue components."
                      " Use jsdom-friendly assertions and behavior-level checks; avoid brittle DOM shape coupling."
                      " Prefer write_file for full test-file rewrites when repair context is unstable."
                      " Do not modify implementation files in WRITE_TESTS."
                )
            return (
                base
                + " Framework-native test contract: this is a backend/runtime test surface."
                  " Generate pytest-compatible Python tests only (test_*.py)."
                  " Keep validation lightweight and directly tied to the requested behavior."
                  " Prefer behavior-oriented assertions over brittle implementation details; avoid requiring exact CSS class names, selector shapes, or DOM nesting unless the task explicitly requires them."
                  " When multiple valid implementations are possible (for example background image vs inline img), encode acceptance checks that allow equivalent outcomes aligned to the task intent."
                  " For existing large or frequently edited test files, prefer write_file with full file contents over fragile line-numbered patch hunks."
                  " Use apply_patch only for short, stable edits."
                  " Remove or update stale assertions when behavior changes so old and new expectations do not conflict in the same suite."
                  " Malformed unified diffs are treated as hard failures in this stage."
                + test_dependency_guard
            )
        if work_item.type == "RUN_TESTS":
            return base + " Keep validation lightweight and directly tied to the requested behavior." + test_dependency_guard
        if "PLAN" in work_item.type:
            return (
                base
                + " This is a planning stage. Do not mutate repository files."
                  " Return only note actions that describe the intended patch and validation sequence."
            )
        if review_stage:
            return (
                base
                + " Focus on whether the change matches the requested scope, whether it introduces regressions, and whether validation evidence is sufficient."
                  " If there are no issues, return note actions confirming the review passed."
            )
        if self._strict_output_contract_mode(work_item):
            base += (
                " Strict recovery mode is active due to prior output-contract failures."
                " Return compact deterministic JSON only and keep the action list minimal."
            )
        return base

    def _build_ai_job_request(
        self,
        work_item: WorkItem,
        context_bundle: dict[str, Any],
        allowed_files: list[str],
        execution_contract: ExecutionContract | None = None,
    ) -> AIJobRequest:
        payload = work_item.payload or {}
        candidate_paths = self._candidate_paths(work_item, context_bundle, allowed_files, execution_contract)
        risk_paths = candidate_paths
        if work_item.type == "CODE_FRONTEND":
            # Frontend work can include backend files in surrounding context packs.
            # Risk gating should key off the intended edit scope, not incidental context.
            scoped_targets = _target_files_from_payload(payload)
            if scoped_targets:
                risk_paths = scoped_targets
        risk_level = self._risk_level_for_work_item(work_item, risk_paths)
        if "PLAN" in work_item.type:
            role = "planner"
            task_type = "planning"
            ambiguity = "high"
            workflow_type = "interactive_planning"
        elif work_item.type in {"REVIEW_DIFF", "PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            role = "reviewer"
            task_type = "review"
            ambiguity = "high" if risk_level == "high" else "medium"
            workflow_type = "pr_review"
        elif work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"}:
            role = "coder"
            task_type = "bugfix"
            ambiguity = "medium"
            workflow_type = "repo_implementation_task"
        elif work_item.type in {"WRITE_TESTS", "RUN_TESTS"}:
            role = "coder"
            task_type = "testing"
            ambiguity = "medium"
            workflow_type = "repo_implementation_task"
        else:
            role = "coder"
            task_type = "implementation"
            ambiguity = "medium"
            workflow_type = "repo_implementation_task"
        metadata = {
            "work_item_type": work_item.type,
            "work_item_key": work_item.key,
            "feature_key": payload.get("feature_key"),
            "surface": payload.get("surface"),
        }
        project_contract = (
            context_bundle.get("meta", {}).get("project_contract")
            if isinstance(context_bundle.get("meta"), dict)
            else None
        )
        if isinstance(project_contract, dict):
            summary = project_contract.get("summary") if isinstance(project_contract.get("summary"), dict) else {}
            if isinstance(summary, dict):
                status = summary.get("status")
                if isinstance(status, str) and status.strip():
                    metadata["project_contract_status"] = status.strip()
                if isinstance(summary.get("enforcement_enabled"), bool):
                    metadata["project_contract_enforcement"] = summary.get("enforcement_enabled")
                mode = _project_contract_enforcement_mode(project_contract)
                metadata["project_contract_enforcement_mode"] = mode
                active_rules = [
                    item
                    for item in summary.get("active_rules", [])
                    if isinstance(item, str) and item.strip()
                ]
                if active_rules:
                    metadata["project_contract_rules"] = active_rules[:8]
            design_packet = _design_context_packet(project_contract)
            metadata["design_experience_blueprint"] = design_packet.get("experience_blueprint")
            metadata["design_visual_tone"] = design_packet.get("visual_tone")
            metadata["design_layout_density"] = design_packet.get("layout_density")
            metadata["design_allowed_components"] = design_packet.get("allowed_components", [])[:12]
        if execution_contract is not None:
            metadata["validation_state"] = execution_contract.validation_state
            metadata["retry_state"] = execution_contract.retry_state
            metadata["budget_mode"] = execution_contract.budget.budget_mode
            metadata["active_budget_partition"] = execution_contract.budget.active_budget_partition
            metadata["recovery_reserve_cost_cents"] = execution_contract.budget.recovery_reserve_cost_cents
            metadata["remaining_recovery_cost_cents"] = execution_contract.budget.remaining_recovery_cost_cents
            if execution_contract.budget.model_tier_cap:
                metadata["max_model_tier_cap"] = execution_contract.budget.model_tier_cap
        recovery_tier = payload.get("recovery_tier")
        if isinstance(recovery_tier, str) and recovery_tier.strip():
            recovery_tier = recovery_tier.strip()
            metadata["recovery_tier"] = recovery_tier
            if recovery_tier == "cheap_recovery":
                metadata["selected_model_tier_override"] = "tier_economy"
                metadata["max_model_tier_cap"] = "tier_economy"
            elif recovery_tier == "code_repair":
                metadata["selected_model_tier_override"] = "tier_standard"
            elif recovery_tier == "deterministic":
                metadata["selected_model_tier_override"] = "tier_economy"
                metadata["max_model_tier_cap"] = "tier_economy"
        return AIJobRequest(
            workflow_type=workflow_type,
            role=role,
            task_type=task_type,
            ambiguity_level=ambiguity,
            risk_level=risk_level,
            tenant_id=work_item.tenant_id,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            feature_key=self._feature_key_for_work_item(work_item),
            surface=self._surface_for_work_item(work_item),
            entrypoint="runtime.codex_executor",
            changed_files=risk_paths,
            tests_failed=work_item.type in {"FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY"},
            metadata=metadata,
        )

    @staticmethod
    def _feature_key_for_work_item(work_item: WorkItem) -> str:
        payload = work_item.payload or {}
        explicit = payload.get("feature_key")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        return work_item.key or work_item.type.lower()

    @staticmethod
    def _surface_for_work_item(work_item: WorkItem) -> str:
        payload = work_item.payload or {}
        explicit = payload.get("surface")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        mapping = {
            "PLAN_DAG": "planning",
            "PLAN_BACKEND_TOPOLOGY": "planning",
            "REVIEW_DIFF": "review",
            "PREVIEW_VALIDATE": "review",
            "REVIEW_INTEGRATION": "review",
            "WRITE_TESTS": "tests",
            "RUN_TESTS": "tests",
            "FIX_TEST_FAILURE": "tests",
            "FIX_LAYOUT_COMPOSITION": "frontend",
            "FIX_ZONE_COMPOSITION": "frontend",
            "FIX_FRONTEND_SYNTAX": "frontend",
            "FIX_VISUAL_QUALITY": "frontend",
            "GENESIS_FOUNDATION": "frontend",
            "CODE_FRONTEND": "frontend",
            "CODE_BACKEND": "backend",
            "GENERATE_ROUTE": "backend",
            "GENERATE_SERVICE": "backend",
            "GENERATE_REPOSITORY": "backend",
            "GENERATE_CAPABILITY_BINDING": "backend",
        }
        return mapping.get(work_item.type, "runtime")

    def _candidate_paths(
        self,
        work_item: WorkItem,
        context_bundle: dict[str, Any],
        allowed_files: list[str],
        execution_contract: ExecutionContract | None = None,
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(paths: list[str]) -> None:
            for path in paths:
                cleaned = (path or "").strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                ordered.append(cleaned)

        payload = work_item.payload or {}
        add(_target_files_from_payload(payload))
        if execution_contract is not None:
            add(list(execution_contract.target_files))
            add(list(execution_contract.allowed_files))
            add(list(execution_contract.related_files))
        add(list(context_bundle.get("files", {}).keys()))
        add(allowed_files)
        for key in ("file", "filepath", "path", "target_file"):
            value = payload.get(key)
            if isinstance(value, str):
                add([value])
            elif isinstance(value, list):
                add([item for item in value if isinstance(item, str)])
        if isinstance(payload.get("files"), list):
            add([item for item in payload["files"] if isinstance(item, str)])
        if isinstance(payload.get("related_files"), list):
            add([item for item in payload["related_files"] if isinstance(item, str)])
        if isinstance(payload.get("failing_test_files"), list):
            add([item for item in payload["failing_test_files"] if isinstance(item, str)])
        artifacts = context_bundle.get("artifacts", {})
        diff_content = artifacts.get("git_diff") or artifacts.get("diff_summary")
        if isinstance(diff_content, str):
            add(self._paths_from_diff(diff_content))
        return ordered[:12]

    def _risk_level_for_work_item(self, work_item: WorkItem, candidate_paths: list[str]) -> str:
        if contains_sensitive_paths(candidate_paths) or work_item.type in {"PREVIEW_VALIDATE", "REVIEW_INTEGRATION"}:
            return "high"
        if work_item.type in {"CODE_BACKEND", "CODE_FRONTEND", "GENERATE_ROUTE", "GENERATE_SERVICE", "GENERATE_REPOSITORY", "GENERATE_CAPABILITY_BINDING", "FIX_TEST_FAILURE", "FIX_LAYOUT_COMPOSITION", "FIX_ZONE_COMPOSITION", "FIX_FRONTEND_SYNTAX", "FIX_VISUAL_QUALITY", "REVIEW_DIFF"} or len(candidate_paths) >= 4:
            return "medium"
        return "low"

    @staticmethod
    def _policy_payload(policy) -> dict[str, Any]:
        return {
            "task_type": policy.task_type,
            "ambiguity_level": policy.ambiguity_level,
            "risk_level": policy.risk_level,
            "max_model_tier": policy.max_model_tier,
            "selected_model_tier": policy.selected_model_tier,
            "max_retries": policy.max_retries,
            "max_context_tokens": policy.max_context_tokens,
            "budget_cents": policy.budget_cents,
            "requires_human_review": policy.requires_human_review,
        }


_DEFAULT_EXECUTOR = CodexExecutor()


async def execute(work_item: WorkItem, context: RunContext) -> TaskResult:
    """Compatibility entrypoint used by older runtime tests and adapters."""
    return await _DEFAULT_EXECUTOR.execute(work_item, context)
