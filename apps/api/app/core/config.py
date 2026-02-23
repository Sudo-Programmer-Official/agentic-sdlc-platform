from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Agentic SDLC API"
    env: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_sdlc"
    db_echo: bool = False
    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1"
    openai_api_key: str | None = None
    llm_temperature: float = 0.2
    health_regen_threshold: float = 60.0  # below this require force for regen
    health_cycles_block: bool = False  # set true to block trace creation when cycles exist

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
