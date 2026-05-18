from __future__ import annotations

import enum
import re
import uuid

from app.operator.schemas import OperatorRequest

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class OperatorIntent(str, enum.Enum):
    CONTENT_UPDATE = "content_update"
    STRUCTURAL_CHANGE = "structural_change"
    PROJECT_STATUS = "project_status"
    RUN_DEBUG = "run_debug"
    ARTIFACT_EXPLAIN = "artifact_explain"
    RUN_COMPARISON = "run_comparison"
    WORKSPACE_STATUS = "workspace_status"
    PROJECT_HEALTH = "project_health"
    REPO_CONTEXT = "repo_context"
    UNKNOWN = "unknown"


def extract_uuid(text: str) -> uuid.UUID | None:
    match = _UUID_RE.search(text)
    if not match:
        return None
    try:
        return uuid.UUID(match.group(0))
    except ValueError:
        return None


def classify_intent(request: OperatorRequest) -> OperatorIntent:
    lowered = request.message.strip().lower()
    if not lowered:
        return OperatorIntent.UNKNOWN
    if "compare" in lowered and "run" in lowered:
        return OperatorIntent.RUN_COMPARISON
    if "workspace" in lowered:
        return OperatorIntent.WORKSPACE_STATUS
    if "health" in lowered:
        return OperatorIntent.PROJECT_HEALTH
    if "artifact" in lowered or "patch" in lowered or "diff" in lowered:
        return OperatorIntent.ARTIFACT_EXPLAIN
    if (
        "repo map" in lowered
        or "repository map" in lowered
        or "codebase" in lowered
        or "search repo" in lowered
        or "search code" in lowered
        or lowered.startswith("find ")
        or lowered.startswith("locate ")
        or lowered.startswith("where is ")
        or lowered.startswith("which file")
        or "component" in lowered
        or "page" in lowered
        or "button" in lowered
    ):
        return OperatorIntent.REPO_CONTEXT
    structural_terms = (
        "add section",
        "add ",
        "section",
        "layout",
        "styling",
        "animation",
        "animated",
        "route",
        "routing",
        "interaction",
        "topology",
    )
    content_terms = (
        "change",
        "update",
        "headline",
        "title",
        "cta",
        "pricing",
        "faq",
        "testimonial",
        "copy",
        "label",
        "button text",
    )
    if any(term in lowered for term in structural_terms):
        return OperatorIntent.STRUCTURAL_CHANGE
    if any(term in lowered for term in content_terms):
        return OperatorIntent.CONTENT_UPDATE
    if (
        "run" in lowered
        or "failed" in lowered
        or "failure" in lowered
        or "latest run" in lowered
        or "last run" in lowered
        or request.context.run_id is not None
        or extract_uuid(request.message) is not None
    ):
        return OperatorIntent.RUN_DEBUG
    if "project" in lowered or "what is going on" in lowered or "status" in lowered:
        return OperatorIntent.PROJECT_STATUS
    return OperatorIntent.UNKNOWN
