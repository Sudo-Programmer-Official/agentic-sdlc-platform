from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from app.runtime.context import RunContext
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
        elif action.type == "apply_patch" and action.patch:
            touched.extend(_paths_from_diff(action.patch))
    return list(dict.fromkeys(touched))


def has_mutating_actions(actions: list[Action]) -> bool:
    return any(action.type in {"write_file", "delete_file", "apply_patch"} for action in actions)


@dataclass(frozen=True)
class PatchGuardDecision:
    touched_files: list[str]
    allowed_files: list[str]
    file_budget: int
    hard_file_budget: int
    violations: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations


def evaluate_patch_guard(
    *,
    actions: list[Action],
    allowed_files: list[str],
    file_budget: int = DEFAULT_MAX_PATCH_FILES,
    hard_file_budget: int = HARD_MAX_PATCH_FILES,
) -> PatchGuardDecision:
    touched_files = extract_action_paths(actions)
    violations: list[str] = []

    if len(touched_files) > hard_file_budget:
        violations.append(
            f"Patch touches {len(touched_files)} files; hard cap is {hard_file_budget}."
        )
    elif len(touched_files) > file_budget:
        violations.append(
            f"Patch touches {len(touched_files)} files; autonomous file budget is {file_budget}."
        )

    if allowed_files:
        extra_files = [path for path in touched_files if path not in allowed_files]
        if extra_files:
            violations.append(
                "Patch touches files outside the planned scope: "
                + ", ".join(extra_files[:8])
            )

    return PatchGuardDecision(
        touched_files=touched_files,
        allowed_files=allowed_files,
        file_budget=file_budget,
        hard_file_budget=hard_file_budget,
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
    return {
        "allowed_files": allowed_files,
        "target_files": target_files or [],
        "scope_mode": scope_mode,
        "file_budget": file_budget,
        "hard_file_budget": hard_file_budget,
        "plan_risk_level": plan_snapshot.get("risk_level"),
        "validation_steps": plan_snapshot.get("validation_steps", []),
    }
