import pytest
from types import SimpleNamespace

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
        await client.generate("system", "user", model="gpt-4.1")


@pytest.mark.anyio
async def test_openai_client_uses_chat_completions_json_mode(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = OpenAIClient()
    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            )

    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    raw, usage = await client.generate("system prompt", "user prompt", model="gpt-4.1", max_tokens=321)

    assert raw == '{"ok":true}'
    assert usage == {"input_tokens": 11, "output_tokens": 7}
    assert captured["model"] == "gpt-4.1"
    assert captured["max_tokens"] == 321
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
