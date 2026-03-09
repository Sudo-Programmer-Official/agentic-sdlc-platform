import pytest

from app.core.config import get_settings
from app.runtime.codex_executor import CodexExecutor
from app.runtime.llm.openai_client import OpenAIClient
from app.runtime.registry import get_executor


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_codex_executor_is_constructed_lazily(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    first = get_executor("codex")
    second = get_executor("codex")

    assert isinstance(first, CodexExecutor)
    assert isinstance(second, CodexExecutor)
    assert first is not second
    assert first._client is None
    assert second._client is None


@pytest.mark.anyio
async def test_openai_client_fails_on_generate_when_key_missing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    client = OpenAIClient()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await client.generate("system", "user")
