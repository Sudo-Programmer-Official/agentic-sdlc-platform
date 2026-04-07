from __future__ import annotations

from app.services.runtime_env_diagnostics import collect_runtime_startup_diagnostics


def test_collect_runtime_startup_diagnostics_reads_github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "2904464")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "dummy-key")
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    diagnostics = collect_runtime_startup_diagnostics("external")

    assert diagnostics.runtime_mode == "external"
    assert diagnostics.runtime_git_auth_mode == "auto"
    assert diagnostics.github_app_id_present is True
    assert diagnostics.github_private_key_present is True
    assert diagnostics.github_webhook_secret_present is False
    assert diagnostics.runtime_git_auth_ready is True
    assert diagnostics.runtime_git_auth_status == "READY"
    assert diagnostics.runtime_git_auth_missing == ()
    assert diagnostics.github_clone_auth_ready is True
    assert diagnostics.github_clone_auth_status == "READY"
    assert diagnostics.github_clone_auth_missing == ()


def test_collect_runtime_startup_diagnostics_reports_missing_clone_auth_requirements(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr("app.services.runtime_env_diagnostics.shutil.which", lambda _name: None)

    diagnostics = collect_runtime_startup_diagnostics("external")

    assert diagnostics.git_binary is None
    assert diagnostics.runtime_git_auth_ready is False
    assert diagnostics.runtime_git_auth_status == "BLOCKED"
    assert diagnostics.runtime_git_auth_missing == ("git",)
    assert diagnostics.github_clone_auth_ready is False
    assert diagnostics.github_clone_auth_status == "BLOCKED"
    assert diagnostics.github_clone_auth_missing == ("git", "GITHUB_APP_ID", "GITHUB_PRIVATE_KEY")


def test_collect_runtime_startup_diagnostics_reports_ssh_mode_ready_without_github_env(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(
        "app.services.runtime_env_diagnostics.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"git", "ssh"} else None,
    )

    diagnostics = collect_runtime_startup_diagnostics("external", "ssh")

    assert diagnostics.runtime_git_auth_mode == "ssh"
    assert diagnostics.git_binary == "/usr/bin/git"
    assert diagnostics.ssh_binary == "/usr/bin/ssh"
    assert diagnostics.runtime_git_auth_ready is True
    assert diagnostics.runtime_git_auth_status == "READY"
    assert diagnostics.runtime_git_auth_missing == ()
    assert diagnostics.github_clone_auth_status == "BLOCKED"


def test_collect_runtime_startup_diagnostics_reports_missing_ssh_binary(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(
        "app.services.runtime_env_diagnostics.shutil.which",
        lambda name: "/usr/bin/git" if name == "git" else None,
    )

    diagnostics = collect_runtime_startup_diagnostics("external", "ssh")

    assert diagnostics.runtime_git_auth_mode == "ssh"
    assert diagnostics.runtime_git_auth_ready is False
    assert diagnostics.runtime_git_auth_status == "BLOCKED"
    assert diagnostics.runtime_git_auth_missing == ("ssh",)
