from __future__ import annotations

import time
import uuid
from collections import defaultdict


_TTL_SECONDS = 20 * 60
_MAX_ITEMS = 12
_hot_context: dict[uuid.UUID, dict] = {}


def _trim(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen[:_MAX_ITEMS]


def record_repo_hot_context(
    project_id: uuid.UUID,
    *,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    subsystems: list[str] | None = None,
    failing_tests: list[str] | None = None,
    patch_clusters: list[str] | None = None,
) -> None:
    current = _hot_context.get(project_id) or {
        "recent_files": [],
        "recent_symbols": [],
        "recent_subsystems": [],
        "recent_failing_tests": [],
        "recent_patch_clusters": [],
    }
    current["recent_files"] = _trim([*(files or []), *current["recent_files"]])
    current["recent_symbols"] = _trim([*(symbols or []), *current["recent_symbols"]])
    current["recent_subsystems"] = _trim([*(subsystems or []), *current["recent_subsystems"]])
    current["recent_failing_tests"] = _trim([*(failing_tests or []), *current["recent_failing_tests"]])
    current["recent_patch_clusters"] = _trim([*(patch_clusters or []), *current["recent_patch_clusters"]])
    current["last_access"] = time.time()
    _hot_context[project_id] = current


def get_repo_hot_context(project_id: uuid.UUID) -> dict:
    current = _hot_context.get(project_id)
    if not current:
        return {
            "recent_files": [],
            "recent_symbols": [],
            "recent_subsystems": [],
            "recent_failing_tests": [],
            "recent_patch_clusters": [],
            "last_access": None,
        }
    if time.time() - float(current.get("last_access", 0)) > _TTL_SECONDS:
        _hot_context.pop(project_id, None)
        return {
            "recent_files": [],
            "recent_symbols": [],
            "recent_subsystems": [],
            "recent_failing_tests": [],
            "recent_patch_clusters": [],
            "last_access": None,
        }
    return current
