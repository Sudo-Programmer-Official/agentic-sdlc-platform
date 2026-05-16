from __future__ import annotations

import re

from app.core.config import get_settings

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slug(value: str, fallback: str) -> str:
    cleaned = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        return fallback
    return cleaned[:32]


def build_workspace_project_preview_host(*, workspace_name: str, project_name: str, workspace_id: str, project_id: str) -> str:
    settings = get_settings()
    suffix = (settings.preview_domain_suffix or "preview.prompt2pr.com").strip().lower()
    workspace_slug = _slug(workspace_name, workspace_id.replace("-", "")[:8])
    project_slug = _slug(project_name, project_id.replace("-", "")[:8])
    return f"{workspace_slug}-{project_slug}.{suffix}"
