from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_sdlc"


class Settings(BaseSettings):
    app_name: str = "Agentic SDLC API"
    env: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    db_echo: bool = False
    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1"
    openai_api_key: str | None = None
    llm_temperature: float = 0.2
    health_regen_threshold: float = 60.0  # below this require force for regen
    health_cycles_block: bool = False  # set true to block trace creation when cycles exist
    runtime_mode: str = "external"  # embedded | external; external falls back if no live workers exist
    max_workitem_concurrency: int = 3
    codex_model: str = "gpt-4.1"
    codex_temperature: float = 0.1
    codex_max_tokens: int = 1200
    codex_timeout_seconds: int = 120
    codex_max_context_bytes: int = 400_000
    codex_max_write_bytes_total: int = 200_000
    codex_redaction_enabled: bool = True
    codex_max_run_tokens: int = 200_000
    max_fix_attempts_per_run: int = 2
    test_command: str = "pytest -q"
    test_timeout_seconds: int = 180
    test_output_max_bytes: int = 200_000
    workspace_base_dir: str = "/tmp/agentic-sdlc-workspaces"
    workspace_repo_source: str | None = None
    workspace_simulation_mode: str = "ephemeral"
    workspace_cleanup_policy: str = "retain"
    workspace_allowed_command_prefixes: str = (
        "git,pytest,python,python3,npm,pnpm,yarn,node,npx,uv,bash,sh,make,go,cargo,eslint,ruff"
    )
    workspace_command_output_max_bytes: int = 200_000
    preview_host: str = "127.0.0.1"
    preview_default_ttl_hours: int = 24
    preview_max_per_project: int = 5
    preview_max_global: int = 20
    git_author_name: str = "Agentic SDLC"
    git_author_email: str = "agentic-sdlc@local"
    runtime_git_auth_mode: str = "auto"  # auto | github_app_https | ssh | none
    github_app_slug: str | None = None
    github_allowed_org: str | None = None
    tenancy_enforcement: bool = False
    run_migrations_on_startup: bool = False
    alembic_config_path: str | None = None
    allowed_origins: List[str] = [
        "https://www.prompt2pr.com",
        "https://prompt2pr.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    model_config = SettingsConfigDict(env_file=(".env", "apps/api/.env"), extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
