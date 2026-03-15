from __future__ import annotations

from app.services.runtime_env_diagnostics import collect_runtime_startup_diagnostics


def test_collect_runtime_startup_diagnostics_reads_github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "2904464")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "dummy-key")
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    diagnostics = collect_runtime_startup_diagnostics("external")

    assert diagnostics.runtime_mode == "external"
    assert diagnostics.github_app_id_present is True
    assert diagnostics.github_private_key_present is True
    assert diagnostics.github_webhook_secret_present is False
