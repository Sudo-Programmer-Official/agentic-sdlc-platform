from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentic_sdlc"
VALID_ASYNCPG_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
ASYNCPG_SSLMODE_ALIASES = {
    "required": "require",
    "enabled": "require",
    "true": "require",
    "1": "require",
    "on": "require",
    "disabled": "disable",
    "false": "disable",
    "0": "disable",
    "off": "disable",
}
ASYNCPG_SSL_ALIASES = {
    "enabled": "require",
    "true": "require",
    "1": "require",
    "on": "require",
    "false": "disable",
    "0": "disable",
    "off": "disable",
}


def normalize_database_url(value: str) -> str:
    raw_value = str(value)
    try:
        url = make_url(raw_value)
    except Exception:
        return raw_value

    if not url.drivername.endswith("+asyncpg"):
        return raw_value

    sslmode = url.query.get("sslmode")
    ssl = url.query.get("ssl")
    normalized_query_updates: dict[str, str] = {}

    if sslmode is not None:
        normalized_sslmode = str(sslmode).lower()
        if normalized_sslmode in VALID_ASYNCPG_SSLMODES:
            normalized_query_value = normalized_sslmode
        else:
            normalized_query_value = ASYNCPG_SSLMODE_ALIASES.get(normalized_sslmode)
        if normalized_query_value is not None and normalized_query_value != sslmode:
            normalized_query_updates["sslmode"] = normalized_query_value

    if ssl is not None and sslmode is None:
        normalized_ssl = ASYNCPG_SSL_ALIASES.get(str(ssl).lower())
        if normalized_ssl is not None:
            normalized_query_updates["sslmode"] = normalized_ssl

    if not normalized_query_updates:
        return raw_value

    return url.difference_update_query(["ssl"]).update_query_dict(normalized_query_updates).render_as_string(
        hide_password=False
    )


class Settings(BaseSettings):
    app_name: str = "Agentic SDLC API"
    env: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 900
    db_connect_timeout_seconds: int = 15
    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1"
    openai_api_key: str | None = None
    llm_temperature: float = 0.2
    ai_tier_premium_model: str = "gpt-4.1"
    ai_tier_standard_model: str = "gpt-4.1-mini"
    ai_tier_economy_model: str = "gpt-4.1-mini"
    ai_tier_premium_input_cents_per_1k_tokens: float = 1.0
    ai_tier_premium_output_cents_per_1k_tokens: float = 4.0
    ai_tier_standard_input_cents_per_1k_tokens: float = 0.3
    ai_tier_standard_output_cents_per_1k_tokens: float = 1.2
    ai_tier_economy_input_cents_per_1k_tokens: float = 0.08
    ai_tier_economy_output_cents_per_1k_tokens: float = 0.3
    ai_budget_premium_cents: float = 25.0
    ai_budget_standard_cents: float = 8.0
    ai_budget_economy_cents: float = 8.0
    ai_budget_background_cents: float = 0.5
    ai_recovery_reserve_fraction: float = 0.35
    ai_recovery_reserve_min_cents: float = 40.0
    ai_max_context_premium_tokens: int = 20_000
    ai_max_context_standard_tokens: int = 20_000
    ai_max_context_economy_tokens: int = 4_000
    ai_default_completion_premium_tokens: int = 2_000
    ai_default_completion_standard_tokens: int = 1_200
    ai_default_completion_economy_tokens: int = 1200
    ai_low_confidence_threshold: float = 0.55
    ai_medium_confidence_threshold: float = 0.8
    ai_human_review_file_threshold: int = 8
    ai_human_review_relaxed_mode: bool = False
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
    codex_frontend_cap_bump_enabled: bool = True
    codex_frontend_retry_max_patch_lines: int = 3_500
    codex_frontend_retry_completion_boost_tokens: int = 3_200
    codex_frontend_retry_completion_cap_tokens: int = 6_000
    codex_bypass_operator_confirmation_required: bool = False
    codex_bypass_app_py_patch_ratio_limit: bool = False
    codex_redaction_enabled: bool = True
    codex_max_run_tokens: int = 400_000
    codex_max_run_cost_cents: float = 120.0
    max_fix_attempts_per_run: int = 2
    test_command: str = "pytest -q"
    test_timeout_seconds: int = 180
    test_output_max_bytes: int = 200_000
    workspace_base_dir: str = "/tmp/agentic-sdlc-workspaces"
    runtime_templates_root: str | None = None
    workspace_repo_source: str | None = None
    workspace_simulation_mode: str = "ephemeral"
    workspace_cleanup_policy: str = "retain"
    workspace_allowed_command_prefixes: str = (
        "git,pytest,python,python3,npm,pnpm,yarn,node,npx,uv,bash,sh,make,go,cargo,eslint,ruff"
    )
    workspace_command_output_max_bytes: int = 200_000
    run_auto_push_branch_on_completion: bool = True
    runtime_never_fail_runs: bool = False
    runtime_goal_orchestration_enabled: bool = False
    foundation_readiness_gate_enabled: bool = False
    runtime_governance_active_product_default_mode: str = "stability"
    runtime_emergency_ship_mode_enabled: bool = False
    runtime_goal_max_recovery_cycles: int = 6
    runtime_validation_replay_max_per_run: int = 1
    runtime_test_retry_max_per_signature: int = 2
    runtime_run_spend_soft_limit_cents: float = 200.0
    runtime_run_spend_hard_limit_cents: float = 500.0
    runtime_recovery_max_attempts_per_work_item: int = 4
    runtime_recovery_max_attempts_per_failure_type: int = 6
    runtime_recovery_max_attempts_per_run: int = 24
    runtime_recovery_max_runtime_minutes: int = 90
    runtime_recovery_max_cost_estimate_cents: float = 160.0
    runtime_recovery_memory_enabled: bool = False
    content_binding_enabled: bool = False
    runtime_recovery_memory_min_samples: int = 3
    runtime_recovery_memory_min_success_rate: float = 0.7
    external_reference_domain_allowlist: str = (
        "docs.python.org,developer.mozilla.org,fastapi.tiangolo.com,docs.github.com,platform.openai.com"
    )
    external_reference_fetch_timeout_seconds: int = 8
    external_reference_max_content_bytes: int = 120_000
    external_reference_max_sanitized_chars: int = 8_000
    external_reference_max_summary_chars: int = 900
    external_reference_max_context_chars: int = 2_000
    external_reference_context_top_k: int = 4
    preview_host: str = "127.0.0.1"
    preview_domain_suffix: str = "preview.prompt2pr.com"
    preview_default_ttl_hours: int = 24
    preview_max_per_project: int = 100
    preview_max_global: int = 20
    preview_autofix_vite_missing_package: bool = True
    git_author_name: str = "Agentic SDLC"
    git_author_email: str = "agentic-sdlc@local"
    runtime_git_auth_mode: str = "auto"  # auto | github_app_https | ssh | none
    github_app_id: str | None = None
    github_private_key: str | None = None
    github_webhook_secret: str | None = None
    github_app_slug: str | None = None
    github_allowed_org: str | None = None
    tenancy_enforcement: bool = False
    workspace_entitlements_enabled: bool = False
    workspace_entitlements_enforce: bool = False
    firebase_project_id: str | None = None
    firebase_auth_enforcement: bool = False
    super_admin_users: str = ""
    run_migrations_on_startup: bool = False
    alembic_config_path: str | None = None
    requirement_memory_refresh_enabled: bool = True
    requirement_memory_refresh_interval_seconds: int = 900
    requirement_memory_refresh_project_limit: int = 50
    requirement_memory_refresh_requirement_limit: int = 100
    memory_synthesizer_enabled: bool = True
    memory_synthesizer_interval_seconds: int = 1800
    memory_synthesizer_project_limit: int = 50
    deployment_runtime_enabled: bool = True
    deployment_runtime_interval_seconds: int = 20
    deployment_runtime_batch_size: int = 20
    deployment_healthcheck_timeout_seconds: int = 8
    deployment_healthcheck_max_retries: int = 3
    workspace_ops_daemon_enabled: bool = True
    workspace_ops_daemon_interval_seconds: int = 86400
    workspace_ops_window_days: int = 30
    allowed_origins: List[str] = [
        "https://www.prompt2pr.com",
        "https://prompt2pr.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url_value(cls, value: str) -> str:
        return normalize_database_url(value)

    model_config = SettingsConfigDict(env_file=(".env", "apps/api/.env"), extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
