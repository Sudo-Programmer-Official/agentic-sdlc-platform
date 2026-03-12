from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_BUILD_VERSION = "build-local"
DEFAULT_BUILD_INFO_PATH = Path(__file__).resolve().parents[1] / "metadata" / "build_history.json"


def _build_info_path() -> Path:
    configured = os.getenv("BUILD_INFO_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_BUILD_INFO_PATH


def _read_manifest() -> dict[str, Any]:
    path = _build_info_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _normalize_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    normalized = dict(entry)
    sha = normalized.get("sha")
    if sha and not normalized.get("short_sha"):
        normalized["short_sha"] = str(sha)[:7]
    return normalized


def get_current_build_info() -> dict[str, Any]:
    manifest = _read_manifest()
    manifest_current = _normalize_entry(manifest.get("current"))

    current = {
        "version": os.getenv("BUILD_VERSION") or (manifest_current or {}).get("version") or DEFAULT_BUILD_VERSION,
        "sha": os.getenv("BUILD_SHA") or (manifest_current or {}).get("sha"),
        "short_sha": os.getenv("BUILD_SHA", "")[:7] or (manifest_current or {}).get("short_sha"),
        "branch": os.getenv("BUILD_BRANCH") or (manifest_current or {}).get("branch"),
        "built_at": os.getenv("BUILD_AT") or (manifest_current or {}).get("built_at"),
        "run_number": _coerce_int(os.getenv("BUILD_RUN_NUMBER")) or (manifest_current or {}).get("run_number"),
        "run_attempt": _coerce_int(os.getenv("BUILD_RUN_ATTEMPT")) or (manifest_current or {}).get("run_attempt"),
        "run_url": os.getenv("BUILD_RUN_URL") or (manifest_current or {}).get("run_url"),
        "title": os.getenv("BUILD_TITLE") or (manifest_current or {}).get("title"),
    }
    if not current["short_sha"] and current["sha"]:
        current["short_sha"] = str(current["sha"])[:7]
    return current


def get_build_history(limit: int = 10) -> list[dict[str, Any]]:
    manifest = _read_manifest()
    current = get_current_build_info()
    raw_history = manifest.get("history") or []

    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for entry in [current, *raw_history]:
        normalized = _normalize_entry(entry)
        if not normalized:
            continue
        key = (normalized.get("version"), normalized.get("sha"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged


def _coerce_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
