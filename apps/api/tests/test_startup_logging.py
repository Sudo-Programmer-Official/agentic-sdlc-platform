import logging

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_app_startup_logs_failure_phase(monkeypatch, caplog):
    async def fake_run_startup_migrations() -> None:
        raise RuntimeError("startup boom")

    monkeypatch.setattr(main_module, "run_startup_migrations", fake_run_startup_migrations)
    caplog.set_level(logging.INFO, logger="app")

    with pytest.raises(RuntimeError, match="startup boom"):
        with TestClient(main_module.create_app()):
            pass

    messages = [record.getMessage() for record in caplog.records]
    assert any("Startup phase=migrations begin" in message for message in messages)
    assert any("Application startup failed during phase=migrations" in message for message in messages)
