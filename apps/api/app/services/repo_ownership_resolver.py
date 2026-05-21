from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_MISSING_OWNERSHIP_MESSAGE = (
    "Repository ownership is not configured yet. "
    "Connect GitHub and choose Personal repository or Organization repository."
)


@dataclass(frozen=True)
class RepoOwnershipResolution:
    owner: str | None
    owner_mode: str | None
    reason: str | None = None
    error_message: str | None = None

    @property
    def resolved(self) -> bool:
        return bool(self.owner)


def resolve_repo_ownership(
    *,
    project_intent: dict[str, Any] | None,
    github_allowed_org: str | None,
    github_adapter: Any,
) -> RepoOwnershipResolution:
    intent = project_intent if isinstance(project_intent, dict) else {}
    requested_mode = str(intent.get("repository_owner_mode") or "").strip().lower()
    explicit_owner = str(intent.get("repo_owner") or "").strip()
    explicit_org = str(intent.get("github_allowed_org") or "").strip()
    configured_org = str(github_allowed_org or "").strip()

    if explicit_owner:
        return RepoOwnershipResolution(owner=explicit_owner, owner_mode=requested_mode or "explicit")
    if requested_mode == "organization":
        if explicit_org:
            return RepoOwnershipResolution(owner=explicit_org, owner_mode="organization")
        if configured_org:
            return RepoOwnershipResolution(owner=configured_org, owner_mode="organization")
    if requested_mode == "personal":
        inferred = _infer_personal_owner(github_adapter)
        if inferred:
            return RepoOwnershipResolution(owner=inferred, owner_mode="personal")
    if explicit_org:
        return RepoOwnershipResolution(owner=explicit_org, owner_mode="organization")
    if configured_org:
        return RepoOwnershipResolution(owner=configured_org, owner_mode="organization")

    # Frictionless fallback: when a single connected GitHub identity exists,
    # default to personal mode without requiring manual owner entry.
    inferred = _infer_personal_owner(github_adapter)
    if inferred:
        return RepoOwnershipResolution(owner=inferred, owner_mode="personal", reason="inferred_from_integration")

    return RepoOwnershipResolution(
        owner=None,
        owner_mode=None,
        reason="ownership_not_configured",
        error_message=_MISSING_OWNERSHIP_MESSAGE,
    )


def _infer_personal_owner(github_adapter: Any) -> str | None:
    if github_adapter is None:
        return None
    store = getattr(github_adapter, "_store", None)
    integration = store.get() if store is not None and hasattr(store, "get") else None
    if integration is None:
        return None
    owner = str(getattr(integration, "org_login", "") or "").strip()
    return owner or None
