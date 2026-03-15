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
    except ValueError as exc:
        assert "installation_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected explicit github_app_https auth mode to require installation_id")


def test_connect_repo_normalizes_github_url_for_ssh_mode(monkeypatch):
    normalized = repo_connector._normalize_repo_url_for_mode(
        repo_url="https://github.com/acme/private-repo",
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
