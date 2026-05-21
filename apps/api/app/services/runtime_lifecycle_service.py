from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.services.activity_log import log_activity

RUNTIME_STATES = [
    "CREATED",
    "TEMPLATE_INSTANTIATED",
    "REPO_CONNECTED",
    "CONTRACT_DERIVED",
    "GOVERNANCE_READY",
    "PREVIEW_READY",
    "ACTIVE",
    "FAILED",
    "PAUSED",
    "REPAIRING",
    "ARCHIVED",
]

ALLOWED_RUNTIME_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"TEMPLATE_INSTANTIATED", "REPO_CONNECTED", "CONTRACT_DERIVED", "FAILED", "PAUSED", "ARCHIVED"},
    "TEMPLATE_INSTANTIATED": {"REPO_CONNECTED", "CONTRACT_DERIVED", "FAILED", "PAUSED", "ARCHIVED"},
    "REPO_CONNECTED": {"CONTRACT_DERIVED", "FAILED", "PAUSED", "ARCHIVED"},
    "CONTRACT_DERIVED": {"GOVERNANCE_READY", "FAILED", "PAUSED", "ARCHIVED"},
    "GOVERNANCE_READY": {"PREVIEW_READY", "FAILED", "PAUSED", "ARCHIVED"},
    "PREVIEW_READY": {"ACTIVE", "FAILED", "PAUSED", "ARCHIVED"},
    "ACTIVE": {"REPAIRING", "PAUSED", "ARCHIVED", "FAILED"},
    "FAILED": {"REPAIRING", "PAUSED", "ARCHIVED"},
    "PAUSED": {"REPAIRING", "ACTIVE", "ARCHIVED", "FAILED"},
    "REPAIRING": {
        "TEMPLATE_INSTANTIATED",
        "REPO_CONNECTED",
        "CONTRACT_DERIVED",
        "GOVERNANCE_READY",
        "PREVIEW_READY",
        "ACTIVE",
        "FAILED",
        "PAUSED",
        "ARCHIVED",
    },
    "ARCHIVED": set(),
}


def _runtime_payload(project: Project) -> dict[str, Any]:
    intent = project.project_intent_json if isinstance(project.project_intent_json, dict) else {}
    payload = intent.get("runtime_lifecycle")
    if isinstance(payload, dict):
        return dict(payload)
    return {
        "state": "CREATED",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "timeline": [],
        "last_error": None,
        "retry_count": 0,
    }


def _write_runtime_payload(project: Project, payload: dict[str, Any]) -> None:
    intent = project.project_intent_json if isinstance(project.project_intent_json, dict) else {}
    merged = dict(intent)
    merged["runtime_lifecycle"] = payload
    project.project_intent_json = merged


async def set_runtime_state(
    session: AsyncSession,
    *,
    project: Project,
    state: str,
    actor_id: str | None,
    diagnostics: dict[str, Any] | None = None,
    error: str | None = None,
) -> bool:
    normalized = str(state or "").strip().upper()
    if normalized not in RUNTIME_STATES:
        raise ValueError(f"Unsupported runtime lifecycle state: {normalized}")

    payload = _runtime_payload(project)
    current = str(payload.get("state") or "CREATED").strip().upper()
    if current == normalized and not error:
        return False
    allowed_next = ALLOWED_RUNTIME_TRANSITIONS.get(current, set())
    if normalized != current and normalized not in allowed_next:
        raise ValueError(f"Invalid runtime lifecycle transition: {current} -> {normalized}")

    now = datetime.now(timezone.utc).isoformat()
    timeline = payload.get("timeline")
    if not isinstance(timeline, list):
        timeline = []
    timeline.append(
        {
            "state": normalized,
            "from_state": current,
            "ts": now,
            "diagnostics": diagnostics or {},
            "error": error,
        }
    )
    payload["state"] = normalized
    payload["updated_at"] = now
    payload["timeline"] = timeline
    if error:
        payload["last_error"] = error
        payload["retry_count"] = int(payload.get("retry_count") or 0) + 1
    elif payload.get("last_error"):
        payload["last_error"] = None

    _write_runtime_payload(project, payload)
    session.add(project)
    await session.flush()
    await log_activity(
        session,
        project_id=project.id,
        entity_type="runtime_lifecycle",
        entity_id=project.id,
        action_type="runtime.lifecycle.transition",
        metadata={
            "from_state": current,
            "to_state": normalized,
            "error": error,
            "diagnostics": diagnostics or {},
        },
        actor=actor_id,
    )
    return True
