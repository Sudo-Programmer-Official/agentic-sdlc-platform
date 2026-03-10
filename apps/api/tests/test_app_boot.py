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
