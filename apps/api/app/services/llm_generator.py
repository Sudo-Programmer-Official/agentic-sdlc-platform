from __future__ import annotations

import json
import uuid
from typing import List, Tuple

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.core.config import get_settings
from app.schemas.generation import TaskGenInput, GeneratedTask

settings = get_settings()


TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["title"],
            },
        }
    },
    "required": ["tasks"],
}


class LLMTaskGenerator:
    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def generate(self, title: str, body: str, opts: TaskGenInput) -> Tuple[List[GeneratedTask], dict]:
        if not self.client:
            # Fallback to mock behavior if API key missing
            from app.services.generation_service import mock_generate_tasks
            tasks, prov = mock_generate_tasks(title, body, opts)
            prov.update(
                {
                    "ai_model_name": self.model,
                    "ai_prompt_hash": prov.get("ai_prompt_hash"),
                    "ai_run_id": prov.get("ai_run_id"),
                    "temperature": opts.temperature,
                }
            )
            return tasks, prov

        system_prompt = (
            "You are an SDLC planner. Return concise, structured tasks derived from the provided document. "
            "Use JSON matching the given schema. Include a confidence score between 0 and 1."
        )

        user_content = f"Document Title: {title}\nDocument Body:\n{body}\nMax tasks: {opts.max_tasks}"

        completion: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            temperature=opts.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            response_format={"type": "json_schema", "json_schema": TASK_SCHEMA},
        )

        raw_json = completion.choices[0].message.content
        data = json.loads(raw_json)
        tasks: List[GeneratedTask] = []
        for item in data.get("tasks", [])[: opts.max_tasks]:
            tasks.append(
                GeneratedTask(
                    title=item.get("title", "").strip() or "Untitled Task",
                    description=item.get("description"),
                    category=item.get("category", "func"),
                    confidence=float(item.get("confidence", 0.75)),
                )
            )

        usage = completion.usage
        prov = {
            "ai_model_name": self.model,
            "ai_prompt_hash": self._hash_prompt(user_content),
            "ai_run_id": str(uuid.uuid4()),
            "temperature": opts.temperature,
            "tokens_prompt": usage.prompt_tokens if usage else None,
            "tokens_completion": usage.completion_tokens if usage else None,
            "response_snapshot": data,
        }
        return tasks, prov

    @staticmethod
    def _hash_prompt(text: str) -> str:
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
