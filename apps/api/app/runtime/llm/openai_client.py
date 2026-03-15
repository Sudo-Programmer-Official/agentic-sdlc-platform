from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import get_settings

log = logging.getLogger("app.runtime.openai_client")


class OpenAIClient:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self._client: Any | None = None
        self.provider = settings.llm_provider or "openai"
        self.temperature = settings.codex_temperature
        self.max_tokens = settings.codex_max_tokens
        self.timeout = settings.codex_timeout_seconds

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("OPENAI_API_KEY missing for Codex executor")
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("openai package is required for Codex executor") from exc
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    @staticmethod
    def sdk_version() -> str:
        try:
            import openai
            return str(getattr(openai, "__version__", "unknown"))
        except Exception:
            return "unknown"

    @staticmethod
    def method_name() -> str:
        return "chat.completions.create"

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> tuple[str, dict]:
        request_kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "response_format": {"type": "json_object"},
        }
        sdk_version = self.sdk_version()
        method_name = self.method_name()
        kwargs_keys = sorted(request_kwargs.keys())
        log.info(
            "OpenAI request prepared sdk_version=%s provider=%s model=%s method=%s kwargs_keys=%s",
            sdk_version,
            self.provider,
            model,
            method_name,
            kwargs_keys,
        )
        try:
            client = self._get_client()
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat.completions.create,
                    **request_kwargs,
                ),
                timeout=self.timeout if timeout is None else timeout,
            )
        except Exception as exc:
            log.exception(
                "OpenAI call failed sdk_version=%s provider=%s model=%s method=%s kwargs_keys=%s exception_class=%s exception=%s",
                sdk_version,
                self.provider,
                model,
                method_name,
                kwargs_keys,
                exc.__class__.__name__,
                str(exc),
                exc_info=exc,
            )
            raise
        usage = {
            "input_tokens": getattr(getattr(resp, "usage", None) or {}, "prompt_tokens", None),
            "output_tokens": getattr(getattr(resp, "usage", None) or {}, "completion_tokens", None),
        }
        choice = (getattr(resp, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", "") or ""
        return content, usage
