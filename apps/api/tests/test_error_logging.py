import logging

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


def test_unhandled_exception_log_includes_type_and_message(caplog):
    app = create_app()

    @app.get("/boom", include_in_schema=False)
    async def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    caplog.set_level(logging.ERROR, logger="app")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    messages = [record.getMessage() for record in caplog.records]
    assert any("type=RuntimeError" in message and "error=boom" in message for message in messages)
