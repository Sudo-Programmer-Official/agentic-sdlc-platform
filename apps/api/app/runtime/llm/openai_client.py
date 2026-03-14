from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings


class OpenAIClient:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self._client: Any | None = None
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
        client = self._get_client()
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                client.responses.create,
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
                response_format={"type": "json_object"},
            ),
            timeout=self.timeout if timeout is None else timeout,
        )
        usage = {
            "input_tokens": getattr(resp, "input_tokens", None)
            or getattr(getattr(resp, "usage", None) or {}, "input_tokens", None),
            "output_tokens": getattr(resp, "output_tokens", None)
            or getattr(getattr(resp, "usage", None) or {}, "output_tokens", None),
        }
        return resp.output_text, usage  # type: ignore[attr-defined]
