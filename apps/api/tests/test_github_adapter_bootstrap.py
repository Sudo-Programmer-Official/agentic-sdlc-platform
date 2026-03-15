from __future__ import annotations

from app.services.vcs.github_app import build_github_adapter
from app.services.vcs.github_store import InMemoryGitHubIntegrationStore


def test_build_github_adapter_allows_runtime_auth_without_webhook_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "dummy")
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    adapter = build_github_adapter(InMemoryGitHubIntegrationStore())

    assert adapter is not None
    assert adapter.verify_signature(b"payload", "sha256=deadbeef") is False
