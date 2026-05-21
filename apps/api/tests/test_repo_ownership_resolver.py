from types import SimpleNamespace

from app.services.repo_ownership_resolver import resolve_repo_ownership


def _adapter_with_owner(owner: str):
    store = SimpleNamespace(get=lambda: SimpleNamespace(org_login=owner))
    return SimpleNamespace(_store=store)


def test_resolve_repo_ownership_prefers_explicit_repo_owner():
    result = resolve_repo_ownership(
        project_intent={"repo_owner": "explicit-owner"},
        github_allowed_org="acme",
        github_adapter=_adapter_with_owner("fallback-owner"),
    )
    assert result.resolved is True
    assert result.owner == "explicit-owner"


def test_resolve_repo_ownership_uses_allowed_org_for_org_mode():
    result = resolve_repo_ownership(
        project_intent={"repository_owner_mode": "organization"},
        github_allowed_org="acme",
        github_adapter=None,
    )
    assert result.resolved is True
    assert result.owner == "acme"
    assert result.owner_mode == "organization"


def test_resolve_repo_ownership_infers_personal_owner_from_integration():
    result = resolve_repo_ownership(
        project_intent={"repository_owner_mode": "personal"},
        github_allowed_org=None,
        github_adapter=_adapter_with_owner("abhishek-jha-ai"),
    )
    assert result.resolved is True
    assert result.owner == "abhishek-jha-ai"
    assert result.owner_mode == "personal"


def test_resolve_repo_ownership_returns_user_friendly_message_when_missing():
    result = resolve_repo_ownership(
        project_intent={"repo_type": "new_repo"},
        github_allowed_org=None,
        github_adapter=None,
    )
    assert result.resolved is False
    assert result.error_message is not None
    assert "Repository ownership is not configured yet." in result.error_message
