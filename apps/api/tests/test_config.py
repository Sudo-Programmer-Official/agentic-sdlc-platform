from app.core.config import Settings, normalize_database_url


def test_settings_read_apps_api_env_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    env_dir = tmp_path / "apps" / "api"
    env_dir.mkdir(parents=True)
    (env_dir / ".env").write_text(
        "OPENAI_API_KEY=test-key\nDATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.openai_api_key == "test-key"
    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/app"


def test_settings_normalize_asyncpg_sslmode_alias():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@db:5432/app?sslmode=required")

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/app?sslmode=require"


def test_settings_normalize_asyncpg_ssl_true_alias():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@db:5432/app?ssl=true")

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/app?sslmode=require"


def test_settings_normalize_asyncpg_ssl_false_alias():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@db:5432/app?ssl=false")

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/app?sslmode=disable"


def test_normalize_database_url_leaves_unknown_sslmode_unchanged():
    database_url = "postgresql+asyncpg://user:pass@db:5432/app?sslmode=custom-value"

    assert normalize_database_url(database_url) == database_url
