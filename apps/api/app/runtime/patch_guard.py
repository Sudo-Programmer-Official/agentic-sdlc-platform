from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re
from typing import Any

from app.runtime.context import RunContext
from app.runtime.execution_contract import ExecutionContract, coerce_execution_contract
from app.runtime.schemas.executor_io import Action

DEFAULT_MAX_PATCH_FILES = 5
HARD_MAX_PATCH_FILES = 15

_SINGULAR_PATH_KEYS = ("file", "filepath", "path", "target_file")
_LIST_PATH_KEYS = ("files", "expected_files")
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_INLINE_STYLE_ATTR_RE = re.compile(r"<[^>]*\sstyle\s*=", re.IGNORECASE)
_CSS_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*[\),]")
_FRONTEND_SUFFIXES = {".html", ".css", ".scss", ".sass", ".less", ".vue", ".tsx", ".jsx", ".js", ".ts"}
_FORBIDDEN_ARTIFACT_PATH_PARTS = {"__pycache__", ".pytest_cache"}
_FORBIDDEN_ARTIFACT_SUFFIXES = {".pyc", ".pyo"}
_MAX_PROJECT_VIOLATION_RECORDS = 64


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def _path_matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_prefix = _normalize_path(prefix)
    if not normalized_path or not normalized_prefix:
        return False
    if normalized_prefix == ".":
        return True
    path_parts = PurePosixPath(normalized_path).parts
    prefix_parts = PurePosixPath(normalized_prefix).parts
    if len(prefix_parts) > len(path_parts):
        return False
    return path_parts[: len(prefix_parts)] == prefix_parts


def _matching_zones(paths: list[str], zones: list[str]) -> list[str]:
    matches: list[str] = []
    for zone in zones:
        if any(_path_matches_prefix(path, zone) for path in paths):
            matches.append(_normalize_path(zone))
    return list(dict.fromkeys(matches))


def _paths_from_payload(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    paths: list[str] = []
    for key in _SINGULAR_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(_normalize_path(value))
    for key in _LIST_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            paths.extend(
                _normalize_path(item)
                for item in value
                if isinstance(item, str) and item.strip()
            )
    return list(dict.fromkeys(paths))


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalize_enforcement_mode(value: Any, *, enabled: bool) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"off", "warn", "strict"}:
            return normalized
    return "warn" if enabled else "off"


def _paths_from_plan_step(step: dict[str, Any] | None) -> list[str]:
    if not isinstance(step, dict):
        return []
    value = step.get("expected_files")
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            _normalize_path(item)
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )


def derive_allowed_files(
    *,
    work_item_id: str,
    work_item_type: str,
    payload: dict[str, Any] | None,
    plan_snapshot: dict[str, Any] | None,
) -> list[str]:
    allowed: list[str] = []
    allowed.extend(_paths_from_payload(payload))
    if isinstance(plan_snapshot, dict):
        expected_files = plan_snapshot.get("expected_files")
        if isinstance(expected_files, list):
            allowed.extend(
                _normalize_path(item)
                for item in expected_files
                if isinstance(item, str) and item.strip()
            )
        for raw_step in plan_snapshot.get("steps", []):
            if not isinstance(raw_step, dict):
                continue
            step_work_item_id = raw_step.get("work_item_id")
            step_type = raw_step.get("work_item_type")
            if (step_work_item_id and str(step_work_item_id) == work_item_id) or (
                not step_work_item_id and step_type == work_item_type
            ):
                allowed.extend(_paths_from_plan_step(raw_step))
    return list(dict.fromkeys(path for path in allowed if path))


def _paths_from_diff(diff: str) -> list[str]:
    paths: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+++ "):
            continue
        path = line.split(maxsplit=1)[1]
        if path.strip() == "/dev/null":
            continue
        if path.startswith(("b/", "a/")):
            path = path[2:]
        paths.append(_normalize_path(path))
    return paths


def _extract_added_lines_from_patch(diff: str, fallback_path: str | None = None) -> dict[str, list[str]]:
    lines_by_file: dict[str, list[str]] = {}
    current_path = _normalize_path(fallback_path) if isinstance(fallback_path, str) and fallback_path.strip() else None
    if current_path:
        lines_by_file.setdefault(current_path, [])
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line.split(maxsplit=1)[1]
            if path.strip() == "/dev/null":
                current_path = None
                continue
            if path.startswith(("b/", "a/")):
                path = path[2:]
            current_path = _normalize_path(path)
            lines_by_file.setdefault(current_path, [])
            continue
        if line.startswith("@@") or line.startswith("--- "):
            continue
        if current_path and line.startswith("+") and not line.startswith("+++ "):
            lines_by_file[current_path].append(line[1:])
    return lines_by_file


def _extract_added_lines(actions: list[Action]) -> dict[str, list[str]]:
    lines_by_file: dict[str, list[str]] = {}
    for action in actions:
        if action.type == "write_file" and action.path and isinstance(action.content, str):
            path = _normalize_path(action.path)
            lines_by_file.setdefault(path, [])
            lines_by_file[path].extend(action.content.splitlines())
        elif action.type == "apply_patch" and isinstance(action.patch, str) and action.patch.strip():
            patch_lines = _extract_added_lines_from_patch(action.patch, fallback_path=action.path)
            for path, lines in patch_lines.items():
                lines_by_file.setdefault(path, [])
                lines_by_file[path].extend(lines)
    return lines_by_file


def _is_frontend_file(path: str) -> bool:
    normalized = _normalize_path(path).lower()
    suffix = PurePosixPath(normalized).suffix.lower()
    return suffix in _FRONTEND_SUFFIXES


def _is_test_file(path: str) -> bool:
    normalized = _normalize_path(path).lower()
    name = PurePosixPath(normalized).name
    return (
        "/tests/" in f"/{normalized}/"
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _artifact_path_violation(path: str) -> str | None:
    normalized = _normalize_path(path)
    parts = {part.lower() for part in PurePosixPath(normalized).parts}
    if parts.intersection(_FORBIDDEN_ARTIFACT_PATH_PARTS):
        return f"Patch may not modify runtime cache artifacts: {normalized}."
    suffix = PurePosixPath(normalized).suffix.lower()
    if suffix in _FORBIDDEN_ARTIFACT_SUFFIXES:
        return f"Patch may not modify compiled artifacts: {normalized}."
    return None


def _coerce_project_contract_enforcement(project_contract: dict[str, Any] | None) -> dict[str, Any]:
    payload = project_contract if isinstance(project_contract, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    enforcement = payload.get("enforcement") if isinstance(payload.get("enforcement"), dict) else {}
    active_rules = _coerce_string_list(enforcement.get("active_rules")) or _coerce_string_list(summary.get("active_rules"))
    active_rule_set = set(active_rules)
    mode = _normalize_enforcement_mode(
        enforcement.get("mode", summary.get("enforcement_mode")),
        enabled=bool(enforcement.get("enabled", summary.get("enforcement_enabled", False))),
    )
    enabled = mode != "off"
    allowed_hex_values = sorted(
        {
            item.strip().lower()
            for item in _coerce_string_list(enforcement.get("allowed_hex_values"))
            if item.strip()
        }
    )
    allowed_css_var_prefixes = [
        item.strip().lower()
        for item in _coerce_string_list(enforcement.get("allowed_css_var_prefixes"))
        if item.strip()
    ]
    blocked_patterns = [
        item
        for item in _coerce_string_list(enforcement.get("blocked_patterns"))
        if item.strip()
    ]
    return {
        "enabled": enabled,
        "mode": mode,
        "active_rules": active_rules,
        "disallow_inline_styles": bool(
            enforcement.get("disallow_inline_styles", "disallow_inline_styles" in active_rule_set)
        ),
        "enforce_color_tokens": bool(
            enforcement.get("enforce_color_tokens", "enforce_color_tokens" in active_rule_set)
        ),
        "require_known_css_variables": bool(
            enforcement.get("require_known_css_variables", "require_known_css_variables" in active_rule_set)
        ),
        "allowed_hex_values": allowed_hex_values,
        "allowed_css_var_prefixes": allowed_css_var_prefixes,
        "blocked_patterns": blocked_patterns,
    }


def _append_project_violation_record(
    records: list[dict[str, Any]],
    *,
    violation_type: str,
    rule: str,
    message: str,
    file: str | None = None,
    value: str | None = None,
) -> None:
    if len(records) >= _MAX_PROJECT_VIOLATION_RECORDS:
        return
    records.append(
        {
            "type": violation_type,
            "rule": rule,
            "file": file,
            "value": value,
            "message": message,
        }
    )


def _project_contract_violations(
    actions: list[Action],
    project_contract: dict[str, Any] | None,
) -> tuple[list[str], list[str], str, list[dict[str, Any]]]:
    enforcement = _coerce_project_contract_enforcement(project_contract)
    if not enforcement["enabled"]:
        return [], [], "off", []

    rules_applied = list(dict.fromkeys(enforcement["active_rules"]))
    violations: list[str] = []
    violation_records: list[dict[str, Any]] = []
    added_lines_by_file = _extract_added_lines(actions)
    inline_style_hits: list[str] = []
    color_hits: dict[str, set[str]] = {}
    css_var_hits: dict[str, set[str]] = {}
    blocked_pattern_hits: dict[str, set[str]] = {}

    for path, lines in added_lines_by_file.items():
        if not _is_frontend_file(path) or _is_test_file(path):
            continue
        for line in lines:
            if enforcement["disallow_inline_styles"] and _INLINE_STYLE_ATTR_RE.search(line):
                inline_style_hits.append(path)
            if enforcement["enforce_color_tokens"] and enforcement["allowed_hex_values"]:
                found_hex = {value.lower() for value in _HEX_COLOR_RE.findall(line)}
                disallowed = found_hex.difference(set(enforcement["allowed_hex_values"]))
                if disallowed:
                    color_hits.setdefault(path, set()).update(disallowed)
            if enforcement["require_known_css_variables"] and enforcement["allowed_css_var_prefixes"]:
                for css_var in _CSS_VAR_RE.findall(line):
                    lowered = css_var.lower()
                    if not any(lowered.startswith(prefix) for prefix in enforcement["allowed_css_var_prefixes"]):
                        css_var_hits.setdefault(path, set()).add(css_var)
            for pattern in enforcement["blocked_patterns"]:
                if pattern in line:
                    blocked_pattern_hits.setdefault(pattern, set()).add(path)

    if inline_style_hits:
        inline_files = list(dict.fromkeys(inline_style_hits))
        violations.append(
            "Project contract disallows inline style attributes in frontend source files: "
            + ", ".join(inline_files[:6])
        )
        for path in inline_files:
            _append_project_violation_record(
                violation_records,
                violation_type="inline_style",
                rule="disallow_inline_styles",
                file=path,
                value="style=",
                message="Inline style attribute added in frontend source.",
            )
    if color_hits:
        examples: list[str] = []
        for path, values in color_hits.items():
            examples.append(f"{path} ({', '.join(sorted(values)[:3])})")
            for color_value in sorted(values):
                _append_project_violation_record(
                    violation_records,
                    violation_type="raw_hex",
                    rule="enforce_color_tokens",
                    file=path,
                    value=color_value,
                    message=f"Found non-token hex color {color_value}.",
                )
        violations.append(
            "Project contract requires brand color tokens; found non-token hex values in: " + ", ".join(examples[:6])
        )
    if css_var_hits:
        examples = []
        for path, values in css_var_hits.items():
            examples.append(f"{path} ({', '.join(sorted(values)[:3])})")
            for css_var in sorted(values):
                _append_project_violation_record(
                    violation_records,
                    violation_type="unknown_css_variable",
                    rule="require_known_css_variables",
                    file=path,
                    value=css_var,
                    message=f"Found CSS variable outside allowed prefixes: {css_var}.",
                )
        violations.append(
            "Project contract requires approved CSS variable prefixes; found unknown variables in: "
            + ", ".join(examples[:6])
        )
    if blocked_pattern_hits:
        examples = []
        for pattern, files in blocked_pattern_hits.items():
            examples.append(f"{pattern} in {', '.join(sorted(files)[:3])}")
            for path in sorted(files):
                _append_project_violation_record(
                    violation_records,
                    violation_type="blocked_pattern",
                    rule="blocked_patterns",
                    file=path,
                    value=pattern,
                    message=f"Matched blocked pattern '{pattern}'.",
                )
        violations.append(
            "Project contract blocked patterns were detected in patch additions: " + "; ".join(examples[:6])
        )

    return violations, rules_applied, str(enforcement.get("mode") or "warn"), violation_records


@dataclass(frozen=True)
class ProjectContractCheckDecision:
    mode: str
    rules_applied: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return self.mode == "strict" and bool(self.violations)


def evaluate_project_contract_precheck(
    *,
    actions: list[Action],
    project_contract: dict[str, Any] | None = None,
) -> ProjectContractCheckDecision:
    violations, rules_applied, mode, records = _project_contract_violations(actions, project_contract)
    return ProjectContractCheckDecision(
        mode=mode,
        rules_applied=rules_applied,
        violations=violations,
        records=records,
    )


def extract_action_paths(actions: list[Action]) -> list[str]:
    touched: list[str] = []
    for action in actions:
        if action.type in {"write_file", "delete_file"} and action.path:
            touched.append(_normalize_path(action.path))
        elif action.type == "apply_patch":
            patch_paths = _paths_from_diff(action.patch) if action.patch else []
            if patch_paths:
                touched.extend(patch_paths)
            elif action.path:
                touched.append(_normalize_path(action.path))
    return list(dict.fromkeys(touched))


def has_mutating_actions(actions: list[Action]) -> bool:
    return any(action.type in {"write_file", "delete_file", "apply_patch"} for action in actions)


@dataclass(frozen=True)
class PatchGuardDecision:
    touched_files: list[str]
    allowed_files: list[str]
    file_budget: int
    hard_file_budget: int
    protected_zones: list[str]
    safe_zones: list[str]
    violations: list[str]
    project_rules_applied: list[str] = field(default_factory=list)
    project_warnings: list[str] = field(default_factory=list)
    project_enforcement_mode: str = "off"
    project_violation_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def evaluate_patch_guard(
    *,
    actions: list[Action],
    allowed_files: list[str] | None = None,
    file_budget: int = DEFAULT_MAX_PATCH_FILES,
    hard_file_budget: int = HARD_MAX_PATCH_FILES,
    protected_paths: list[str] | None = None,
    safe_paths: list[str] | None = None,
    contract: ExecutionContract | dict | None = None,
    project_contract: dict[str, Any] | None = None,
) -> PatchGuardDecision:
    resolved_contract = coerce_execution_contract(contract)
    resolved_allowed_files = (
        list(resolved_contract.allowed_files)
        if resolved_contract is not None and resolved_contract.allowed_files
        else list(allowed_files or [])
    )
    resolved_file_budget = (
        int(resolved_contract.file_budget)
        if resolved_contract is not None and resolved_contract.file_budget > 0
        else int(file_budget)
    )
    resolved_hard_file_budget = (
        max(resolved_file_budget, int(resolved_contract.hard_file_budget))
        if resolved_contract is not None and resolved_contract.hard_file_budget > 0
        else int(hard_file_budget)
    )
    resolved_protected_paths = (
        list(resolved_contract.protected_paths)
        if resolved_contract is not None and resolved_contract.protected_paths
        else list(protected_paths or [])
    )
    resolved_safe_paths = (
        list(resolved_contract.safe_paths)
        if resolved_contract is not None and resolved_contract.safe_paths
        else list(safe_paths or [])
    )
    touched_files = extract_action_paths(actions)
    violations: list[str] = []
    protected_zones = _matching_zones(touched_files, resolved_protected_paths)
    safe_zones = _matching_zones(touched_files, resolved_safe_paths)

    if len(touched_files) > resolved_hard_file_budget:
        violations.append(
            f"Patch touches {len(touched_files)} files; hard cap is {resolved_hard_file_budget}."
        )
    elif len(touched_files) > resolved_file_budget:
        violations.append(
            f"Patch touches {len(touched_files)} files; autonomous file budget is {resolved_file_budget}."
        )

    if resolved_allowed_files:
        extra_files = [path for path in touched_files if path not in resolved_allowed_files]
        if extra_files:
            violations.append(
                "Patch touches files outside the planned scope: "
                + ", ".join(extra_files[:8])
            )
    artifact_violations = [
        message
        for message in (_artifact_path_violation(path) for path in touched_files)
        if message is not None
    ]
    violations.extend(artifact_violations)
    if protected_zones:
        violations.append(
            "Patch touches protected architecture zones that require a narrower plan or explicit review: "
            + ", ".join(protected_zones[:8])
        )
    contract_check = evaluate_project_contract_precheck(actions=actions, project_contract=project_contract)
    project_warnings: list[str] = []
    project_violation_records: list[dict[str, Any]] = [
        {
            **record,
            "mode": contract_check.mode,
            "blocking": contract_check.blocking,
        }
        for record in contract_check.records
    ]
    if contract_check.violations:
        if contract_check.blocking:
            violations.extend(contract_check.violations)
        else:
            project_warnings.extend(contract_check.violations)

    return PatchGuardDecision(
        touched_files=touched_files,
        allowed_files=resolved_allowed_files,
        file_budget=resolved_file_budget,
        hard_file_budget=resolved_hard_file_budget,
        protected_zones=protected_zones,
        safe_zones=safe_zones,
        violations=violations,
        project_rules_applied=contract_check.rules_applied,
        project_warnings=project_warnings,
        project_enforcement_mode=contract_check.mode,
        project_violation_records=project_violation_records,
    )


def build_patch_guard_meta(
    context: RunContext,
    allowed_files: list[str],
    *,
    file_budget: int = DEFAULT_MAX_PATCH_FILES,
    hard_file_budget: int = HARD_MAX_PATCH_FILES,
    scope_mode: str | None = None,
    target_files: list[str] | None = None,
) -> dict[str, Any]:
    plan_snapshot = context.plan_snapshot if isinstance(context.plan_snapshot, dict) else {}
    contract = context.execution_contract
    architecture = context.architecture_profile if isinstance(context.architecture_profile, dict) else {}
    project_contract = context.project_contract if isinstance(context.project_contract, dict) else {}
    project_summary = project_contract.get("summary") if isinstance(project_contract.get("summary"), dict) else {}
    project_enforcement = project_contract.get("enforcement") if isinstance(project_contract.get("enforcement"), dict) else {}
    project_enforcement_mode = _normalize_enforcement_mode(
        project_enforcement.get("mode", project_summary.get("enforcement_mode")),
        enabled=bool(project_enforcement.get("enabled", project_summary.get("enforcement_enabled", False))),
    )
    return {
        "allowed_files": (
            list(contract.allowed_files)
            if contract is not None and contract.allowed_files
            else allowed_files
        ),
        "target_files": target_files or [],
        "scope_mode": contract.scope_mode if contract is not None else scope_mode,
        "file_budget": contract.file_budget if contract is not None else file_budget,
        "hard_file_budget": contract.hard_file_budget if contract is not None else hard_file_budget,
        "plan_risk_level": contract.risk_level if contract is not None else plan_snapshot.get("risk_level"),
        "validation_steps": (
            list(contract.validation_steps)
            if contract is not None
            else plan_snapshot.get("validation_steps", [])
        ),
        "validation_state": contract.validation_state if contract is not None else None,
        "retry_state": contract.retry_state if contract is not None else None,
        "protected_paths": (
            list(contract.protected_paths)
            if contract is not None
            else architecture.get("protected_paths", [])
        ),
        "safe_paths": (
            list(contract.safe_paths)
            if contract is not None
            else architecture.get("safe_paths", [])
        ),
        "validation_recipe_index": (
            {name: {"paths": []} for name in contract.validation_recipes}
            if contract is not None
            else architecture.get("validation_recipe_index", {})
        ),
        "command_index": (
            {key: dict(value) for key, value in contract.command_index.items()}
            if contract is not None
            else architecture.get("command_index", {})
        ),
        "architecture_summary": architecture.get("summary"),
        "project_contract_summary": project_summary,
        "project_contract_enforcement": project_enforcement,
        "project_contract_enforcement_mode": project_enforcement_mode,
        "budget": contract.budget.to_dict() if contract is not None else None,
    }
