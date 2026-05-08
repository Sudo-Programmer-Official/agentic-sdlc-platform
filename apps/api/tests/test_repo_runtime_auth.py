from __future__ import annotations

import types
from pathlib import Path

import pytest

from app.services import repo_connector
from app.services.vcs.github_app import GitHubAppAdapter
from app.services.vcs.github_store import InMemoryGitHubIntegrationStore


def _github_adapter(monkeypatch) -> GitHubAppAdapter:
    adapter = GitHubAppAdapter(
        app_id="1",
        private_key_pem="dummy",
        webhook_secret="secret",
        allowed_org=None,
        store=InMemoryGitHubIntegrationStore(),
    )
    monkeypatch.setattr(adapter, "get_installation_token", lambda installation_id: "ghs_test_token")
    return adapter


def test_resolve_repo_runtime_access_uses_github_app_https(monkeypatch):
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="github_app_https"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: _github_adapter(monkeypatch))

    access = repo_connector.resolve_repo_runtime_access(
        provider="github",
        repo_url="https://github.com/acme/private-repo.git",
        repo_full_name="acme/private-repo",
        installation_id=1234,
    )

    assert access.auth_mode == "github_app_https"
    assert access.clean_repo_url == "https://github.com/acme/private-repo.git"
    assert access.transport_url == "https://github.com/acme/private-repo.git"
    assert access.git_config
    key, value = access.git_config[0]
    assert key == "http.https://github.com/.extraheader"
    assert value.startswith("AUTHORIZATION: Basic ")
    assert access.token_generated is True
    assert access.credential_strategy == "http.extraheader"


def test_resolve_repo_runtime_access_requires_installation_for_explicit_github_app_https(monkeypatch):
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="github_app_https"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: _github_adapter(monkeypatch))

    try:
        repo_connector.resolve_repo_runtime_access(
            provider="github",
            repo_url="https://github.com/acme/private-repo.git",
            repo_full_name="acme/private-repo",
            installation_id=None,
        )
    except RuntimeError as exc:
        assert "installation_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected explicit github_app_https auth mode to require installation_id")


def test_connect_repo_preserves_https_url_for_ssh_mode():
    normalized = repo_connector._normalize_repo_url_for_mode(
        repo_url="https://github.com/acme/private-repo",
        repo_full_name="acme/private-repo",
        auth_mode="ssh",
    )
    assert normalized == "https://github.com/acme/private-repo.git"


def test_connect_repo_normalizes_ssh_url_for_ssh_mode():
    normalized = repo_connector._normalize_repo_url_for_mode(
        repo_url="git@github.com:acme/private-repo",
        repo_full_name="acme/private-repo",
        auth_mode="ssh",
    )
    assert normalized == "git@github.com:acme/private-repo.git"


def test_prepare_workspace_repo_passes_git_config_for_clone(monkeypatch, tmp_path: Path):
    adapter = _github_adapter(monkeypatch)
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="github_app_https"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: adapter)

    calls: list[tuple[list[str], tuple[tuple[str, str], ...]]] = []

    def fake_run_git(args, cwd=None, *, git_config=None):
        calls.append((list(args), tuple(git_config or ())))
        if args[:1] == ["clone"]:
            target = Path(args[-1])
            (target / ".git").mkdir(parents=True, exist_ok=True)
        return ""

    monkeypatch.setattr(repo_connector, "_run_git", fake_run_git)

    repo_connector.prepare_workspace_repo(
        repo_dir=tmp_path / "repo",
        provider="github",
        repo_url="https://github.com/acme/private-repo.git",
        default_branch="main",
        repo_full_name="acme/private-repo",
        installation_id=1234,
        work_branch="run/test",
    )

    clone_call = calls[0]
    assert clone_call[0][0] == "clone"
    assert clone_call[1]


def test_resolve_repo_runtime_access_falls_back_to_default_installation_id(monkeypatch):
    adapter = _github_adapter(monkeypatch)
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="auto"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: adapter)
    monkeypatch.setattr(repo_connector, "get_default_installation_id", lambda provider: 9876)

    access = repo_connector.resolve_repo_runtime_access(
        provider="github",
        repo_url="https://github.com/acme/private-repo.git",
        repo_full_name="acme/private-repo",
        installation_id=None,
    )

    assert access.auth_mode == "github_app_https"
    assert access.installation_id == 9876
    assert access.token_generated is True
    assert access.git_config
    assert access.selection_reason == "github_app_installation_token"


def test_resolve_repo_runtime_access_fails_closed_when_installation_is_present_but_adapter_is_missing(monkeypatch):
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="auto"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: None)
    monkeypatch.setattr(repo_connector, "_lazy_github_adapter_from_env", lambda: None)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="github_app_adapter_unconfigured"):
        repo_connector.resolve_repo_runtime_access(
            provider="github",
            repo_url="https://github.com/acme/private-repo.git",
            repo_full_name="acme/private-repo",
            installation_id=1234,
        )


def test_resolve_repo_runtime_access_fails_closed_when_installation_token_generation_fails(monkeypatch):
    adapter = _github_adapter(monkeypatch)
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="auto"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: adapter)
    monkeypatch.setattr(adapter, "get_installation_token", lambda installation_id: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="github_app_token_generation_failed:RuntimeError"):
        repo_connector.resolve_repo_runtime_access(
            provider="github",
            repo_url="https://github.com/acme/private-repo.git",
            repo_full_name="acme/private-repo",
            installation_id=1234,
        )


def test_resolve_repo_runtime_access_allows_plain_mode_even_with_installation_id(monkeypatch):
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="none"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: None)
    monkeypatch.setattr(repo_connector, "_lazy_github_adapter_from_env", lambda: None)

    access = repo_connector.resolve_repo_runtime_access(
        provider="github",
        repo_url="https://github.com/acme/public-repo.git",
        repo_full_name="acme/public-repo",
        installation_id=1234,
    )

    assert access.auth_mode == "plain"
    assert access.transport_url == "https://github.com/acme/public-repo.git"


def test_resolve_repo_runtime_access_public_https_strategy_overrides_ssh_runtime(monkeypatch):
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="ssh"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: None)
    monkeypatch.setattr(repo_connector, "_lazy_github_adapter_from_env", lambda: None)

    access = repo_connector.resolve_repo_runtime_access(
        provider="github",
        repo_url="https://github.com/acme/public-repo.git",
        repo_full_name="acme/public-repo",
        installation_id=1234,
        auth_strategy="public_https",
    )

    assert access.auth_mode == "plain"
    assert access.selection_reason == "github_app_unavailable_or_not_applicable"
    assert access.transport_url == "https://github.com/acme/public-repo.git"


def test_preflight_repo_access_uses_same_prepare_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="ssh"),
    )
    calls: list[list[str]] = []

    def fake_run_git(args, cwd=None, *, git_config=None):
        calls.append(list(args))
        if args[:1] == ["clone"]:
            target = Path(args[-1])
            (target / ".git").mkdir(parents=True, exist_ok=True)
        return ""

    monkeypatch.setattr(repo_connector, "_run_git", fake_run_git)

    result = repo_connector.preflight_repo_access(
        provider="github",
        repo_url="https://github.com/acme/public-repo.git",
        repo_full_name="acme/public-repo",
        default_branch="main",
        installation_id=1234,
        auth_strategy="public_https",
    )

    assert result.ok is True
    assert result.auth_strategy == "public_https"
    assert result.auth_mode == "plain"
    assert calls[0] == ["ls-remote", "--heads", "https://github.com/acme/public-repo.git", "main"]
    assert calls[1][0] == "clone"


def test_resolve_repo_runtime_access_uses_lazy_env_adapter_when_provider_registry_is_empty(monkeypatch):
    adapter = _github_adapter(monkeypatch)
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="auto"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: None)
    monkeypatch.setattr(repo_connector, "_lazy_github_adapter_from_env", lambda: adapter)

    access = repo_connector.resolve_repo_runtime_access(
        provider="github",
        repo_url="https://github.com/acme/private-repo.git",
        repo_full_name="acme/private-repo",
        installation_id=1234,
    )

    assert access.auth_mode == "github_app_https"
    assert access.token_generated is True
    assert access.adapter_kind == "GitHubAppAdapter"


def test_push_branch_passes_git_config_for_github_app_https(monkeypatch, tmp_path: Path):
    adapter = _github_adapter(monkeypatch)
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="github_app_https"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: adapter)

    calls: list[tuple[list[str], tuple[tuple[str, str], ...]]] = []

    def fake_run_git(args, cwd=None, *, git_config=None):
        calls.append((list(args), tuple(git_config or ())))
        return ""

    monkeypatch.setattr(repo_connector, "_run_git", fake_run_git)

    repo_connector.push_branch(
        tmp_path,
        "run/test",
        provider="github",
        repo_url="https://github.com/acme/private-repo.git",
        repo_full_name="acme/private-repo",
        installation_id=1234,
    )

    assert len(calls) == 1
    assert calls[0][0] == ["push", "-u", "origin", "run/test"]
    assert calls[0][1]
    assert calls[0][1][0][0] == "http.https://github.com/.extraheader"
    assert calls[0][1][0][1].startswith("AUTHORIZATION: Basic ")


def test_run_git_requires_runtime_git_binary(monkeypatch):
    monkeypatch.setattr(repo_connector.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="git binary is unavailable in the API runtime"):
        repo_connector._run_git(["status"])


def test_prepare_workspace_repo_logs_redacted_clone_auth(monkeypatch, tmp_path: Path, caplog):
    adapter = _github_adapter(monkeypatch)
    monkeypatch.setattr(
        repo_connector,
        "get_settings",
        lambda: types.SimpleNamespace(runtime_git_auth_mode="github_app_https"),
    )
    monkeypatch.setattr(repo_connector, "get_vcs_adapter", lambda provider: adapter)

    def fake_run_git(args, cwd=None, *, git_config=None):
        if args[:1] == ["clone"]:
            target = Path(args[-1])
            (target / ".git").mkdir(parents=True, exist_ok=True)
        return ""

    monkeypatch.setattr(repo_connector, "_run_git", fake_run_git)

    with caplog.at_level("INFO", logger="app.repo_connector"):
        repo_connector.prepare_workspace_repo(
            repo_dir=tmp_path / "repo",
            provider="github",
            repo_url="https://github.com/acme/private-repo.git",
            default_branch="main",
            repo_full_name="acme/private-repo",
            installation_id=1234,
            work_branch="run/test",
        )

    assert "token_generated=True" in caplog.text
    assert "git_config_present=True" in caplog.text
    assert "AUTHORIZATION: Basic [redacted]" in caplog.text
    assert "ghs_test_token" not in caplog.text
