from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import Settings, get_settings


log = logging.getLogger("app.startup")


def _escape_ini_value(value: str) -> str:
    # Alembic uses ConfigParser interpolation, so literal percent signs in URLs
    # must be doubled before set_main_option().
    return value.replace("%", "%%")


def resolve_alembic_config_path(settings: Settings | None = None) -> Path | None:
    settings = settings or get_settings()
    if settings.alembic_config_path:
        path = Path(settings.alembic_config_path).expanduser().resolve()
        return path if path.exists() else None

    for base in Path(__file__).resolve().parents:
        for candidate in (
            base / "alembic.ini",
            base / "api" / "alembic.ini",
            base / "apps" / "api" / "alembic.ini",
        ):
            if candidate.exists():
                return candidate
    return None


def build_alembic_config(settings: Settings | None = None) -> Config:
    settings = settings or get_settings()
    config_path = resolve_alembic_config_path(settings)
    if config_path is None:
        raise RuntimeError("Alembic config file not found; cannot apply startup migrations.")

    cfg = Config(str(config_path))
    cfg.set_main_option("script_location", _escape_ini_value(str(config_path.parent / "alembic")))
    cfg.set_main_option("sqlalchemy.url", _escape_ini_value(settings.database_url))
    return cfg


async def run_startup_migrations() -> None:
    settings = get_settings()
    if not settings.run_migrations_on_startup:
        return

    cfg = build_alembic_config(settings)
    log.info("Applying database migrations before serving requests.")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    log.info("Database migrations are up to date.")
