from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from app.runtime.context import RunContext
from app.runtime.execution_contract import ExecutionContract, coerce_execution_contract
from app.runtime.schemas.executor_io import Action

DEFAULT_MAX_PATCH_FILES = 5
HARD_MAX_PATCH_FILES = 15

_SINGULAR_PATH_KEYS = ("file", "filepath", "path", "target_file")
_LIST_PATH_KEYS = ("files", "expected_files")


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
    if protected_zones:
        violations.append(
            "Patch touches protected architecture zones that require a narrower plan or explicit review: "
            + ", ".join(protected_zones[:8])
        )

    return PatchGuardDecision(
        touched_files=touched_files,
        allowed_files=resolved_allowed_files,
        file_budget=resolved_file_budget,
        hard_file_budget=resolved_hard_file_budget,
        protected_zones=protected_zones,
        safe_zones=safe_zones,
        violations=violations,
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
        "budget": contract.budget.to_dict() if contract is not None else None,
    }
