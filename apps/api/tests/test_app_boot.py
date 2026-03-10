import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_app_boots_and_serves_health():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_www_prompt2pr_origin_is_allowed_for_store_routes(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", '["https://prompt2pr.com"]')
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/v1/store/projects",
            headers={
                "Origin": "https://www.prompt2pr.com",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://www.prompt2pr.com"


def test_non_local_env_requires_explicit_database_url(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL must be set"):
        create_app()
