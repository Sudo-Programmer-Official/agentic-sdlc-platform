import logging

import pytest

from app.core.config import get_settings
from app import startup


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_run_startup_migrations_invokes_alembic_upgrade(monkeypatch, tmp_path):
    alembic_ini = tmp_path / "alembic.ini"
    alembic_ini.write_text("[alembic]\nscript_location = alembic\n", encoding="utf-8")

    seen: dict[str, str] = {}

    def fake_upgrade(cfg, revision):
        seen["config_file_name"] = cfg.config_file_name
        seen["script_location"] = cfg.get_main_option("script_location")
        seen["revision"] = revision

    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "true")
    monkeypatch.setenv("ALEMBIC_CONFIG_PATH", str(alembic_ini))
    monkeypatch.setattr(startup.command, "upgrade", fake_upgrade)

    await startup.run_startup_migrations()

    assert seen == {
        "config_file_name": str(alembic_ini),
        "script_location": str(tmp_path / "alembic"),
        "revision": "head",
    }


def test_build_alembic_config_preserves_percent_encoded_database_urls(monkeypatch, tmp_path):
    alembic_ini = tmp_path / "alembic.ini"
    alembic_ini.write_text("[alembic]\nscript_location = alembic\n", encoding="utf-8")

    database_url = "postgresql+asyncpg://postgres:DevPassword123%21@db.example.com:5432/app?ssl=require"
    monkeypatch.setenv("ALEMBIC_CONFIG_PATH", str(alembic_ini))
    monkeypatch.setenv("DATABASE_URL", database_url)

    cfg = startup.build_alembic_config()

    assert cfg.get_main_option("sqlalchemy.url") == database_url


@pytest.mark.anyio
async def test_run_startup_migrations_is_noop_when_disabled(monkeypatch):
    called = False

    def fake_upgrade(cfg, revision):
        nonlocal called
        called = True

    monkeypatch.setattr(startup.command, "upgrade", fake_upgrade)

    await startup.run_startup_migrations()

    assert called is False


@pytest.mark.anyio
async def test_run_startup_migrations_logs_failure_context(monkeypatch, tmp_path, caplog):
    alembic_ini = tmp_path / "alembic.ini"
    alembic_ini.write_text("[alembic]\nscript_location = alembic\n", encoding="utf-8")

    def fake_upgrade(cfg, revision):
        raise RuntimeError("boom")

    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "true")
    monkeypatch.setenv("ALEMBIC_CONFIG_PATH", str(alembic_ini))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:supersecret@db.example.com:5432/app")
    monkeypatch.setattr(startup.command, "upgrade", fake_upgrade)
    caplog.set_level(logging.INFO, logger="app.startup")

    with pytest.raises(RuntimeError, match="boom"):
        await startup.run_startup_migrations()

    messages = [record.getMessage() for record in caplog.records]
    assert any("Applying database migrations before serving requests" in message for message in messages)
    assert any(
        "Startup migration failed" in message and "postgresql+asyncpg://db.example.com:5432/app" in message
        for message in messages
    )
    assert all("supersecret" not in message for message in messages)
