from __future__ import annotations

import asyncio
import json
import uuid
from typing import List, Tuple

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.generation import TaskGenInput, GeneratedTask
from app.services.ai_policy import AIJobManager, AIJobRequest, AIPolicyError, estimate_tokens, is_retryable_error, retry_error_kind

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


def _task_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "task_generation",
            "schema": TASK_SCHEMA,
        },
    }


class LLMTaskGenerator:
    def __init__(
        self,
        *,
        session: AsyncSession | None = None,
        tenant_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
    ) -> None:
        self.provider = settings.llm_provider
        self.temperature = settings.llm_temperature
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.document_id = document_id
        self._session = session
        self._job_manager = AIJobManager.from_session(session) if session is not None else AIJobManager()

    async def generate(self, title: str, body: str, opts: TaskGenInput) -> Tuple[List[GeneratedTask], dict]:
        job_request = AIJobRequest(
            workflow_type="interactive_planning",
            role="planner",
            task_type="planning",
            ambiguity_level="high",
            risk_level="medium",
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            document_id=self.document_id,
            user_triggered=True,
            metadata={"document_title": title, "max_tasks": opts.max_tasks},
        )
        cache_context = await self._job_manager.load_cached_context_fragments(job_request, session=self._session)

        system_prompt = (
            "You are an SDLC planner. Return concise, structured tasks derived from the provided document. "
            "Use JSON matching the given schema. Include a confidence score between 0 and 1."
        )
        body_excerpt = body.strip()
        policy = self._job_manager.route_job(job_request)
        max_chars = max(256, policy.max_context_tokens * 4)
        if len(body_excerpt) > max_chars:
            body_excerpt = body_excerpt[:max_chars]

        project_context = "\n".join(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in cache_context.fragments.items()
            if value
        )
        user_content = (
            f"Document Title: {title}\n"
            f"Document Body:\n{body_excerpt}\n"
            f"Max tasks: {opts.max_tasks}\n"
        )
        if project_context:
            user_content += f"\nRelevant Project Context:\n{project_context}\n"

        prepared = await self._job_manager.prepare_job(
            job_request,
            system_prompt=system_prompt,
            user_prompt=user_content,
            filters_used=["document_excerpt_compression", "cached_project_context"],
            cache_hit_count=cache_context.cache_hits,
            completion_token_estimate=policy.max_context_tokens // 10,
            block_on_human_review=False,
            session=self._session,
        )
        if prepared.stop_reason:
            raise AIPolicyError(
                prepared.stop_reason,
                prepared.next_action or "Reduce scope and retry.",
                job_id=prepared.job_id,
                details={"estimated_cost_cents": prepared.estimated_cost_cents},
            )

        if not self.client or not prepared.model_name:
            from app.services.generation_service import mock_generate_tasks

            tasks, prov = mock_generate_tasks(title, body_excerpt, opts)
            avg_confidence = round(sum(task.confidence for task in tasks) / len(tasks), 3) if tasks else None
            await self._job_manager.complete_job(
                prepared.job_id,
                input_tokens=0,
                output_tokens=0,
                confidence_score=avg_confidence,
                details={"execution_mode": "deterministic_fallback"},
                approval_state="pending" if avg_confidence and avg_confidence < settings.ai_low_confidence_threshold else None,
                session=self._session,
            )
            prov.update(
                {
                    "ai_model_name": prepared.model_name or "deterministic-fallback",
                    "ai_job_id": str(prepared.job_id),
                    "ai_selected_tier": prepared.policy.selected_model_tier,
                    "ai_policy": self._policy_payload(prepared.policy),
                    "temperature": opts.temperature,
                }
            )
            return tasks, prov

        parse_retry_used = False
        current_user_prompt = user_content
        completion: ChatCompletion | None = None
        data: dict | None = None
        for attempt in range(prepared.policy.max_retries + 1):
            await self._job_manager.record_attempt(prepared.job_id, session=self._session)
            try:
                completion = await self.client.chat.completions.create(
                    model=prepared.model_name,
                    temperature=opts.temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": current_user_prompt},
                    ],
                    response_format=_task_response_format(),
                )
                raw_json = completion.choices[0].message.content or "{}"
                data = json.loads(raw_json)
                break
            except json.JSONDecodeError as exc:
                if not parse_retry_used and attempt < prepared.policy.max_retries:
                    parse_retry_used = True
                    await self._job_manager.record_retry(
                        prepared.job_id,
                        "structured_parser_failure",
                        session=self._session,
                    )
                    current_user_prompt = (
                        f"{user_content}\nRespond with EXACTLY one JSON object matching the schema and no prose."
                    )
                    continue
                await self._job_manager.fail_job(
                    prepared.job_id,
                    reason="output_contract_invalid",
                    next_action="Narrow the document excerpt or inspect the prompt contract.",
                    error_kind="structured_parser_failure",
                    session=self._session,
                )
                raise AIPolicyError(
                    "output_contract_invalid",
                    "Narrow the document excerpt or inspect the prompt contract.",
                    job_id=prepared.job_id,
                ) from exc
            except Exception as exc:
                if attempt < prepared.policy.max_retries and is_retryable_error(exc):
                    await self._job_manager.record_retry(
                        prepared.job_id,
                        retry_error_kind(exc),
                        session=self._session,
                    )
                    await asyncio.sleep(min(2 ** attempt, 3))
                    continue
                await self._job_manager.fail_job(
                    prepared.job_id,
                    reason="model_call_failed",
                    next_action="Retry with smaller context or inspect the upstream model failure.",
                    error_kind=retry_error_kind(exc),
                    session=self._session,
                )
                raise

        tasks: List[GeneratedTask] = []
        for item in (data or {}).get("tasks", [])[: opts.max_tasks]:
            tasks.append(
                GeneratedTask(
                    title=item.get("title", "").strip() or "Untitled Task",
                    description=item.get("description"),
                    category=item.get("category", "func"),
                    confidence=float(item.get("confidence", 0.75)),
                )
            )

        avg_confidence = round(sum(task.confidence for task in tasks) / len(tasks), 3) if tasks else None
        usage = completion.usage if completion else None
        await self._job_manager.complete_job(
            prepared.job_id,
            input_tokens=usage.prompt_tokens if usage else estimate_tokens(system_prompt + current_user_prompt),
            output_tokens=usage.completion_tokens if usage else 0,
            confidence_score=avg_confidence,
            details={"execution_mode": "model"},
            approval_state="pending" if avg_confidence and avg_confidence < settings.ai_low_confidence_threshold else None,
            session=self._session,
        )
        prov = {
            "ai_model_name": prepared.model_name,
            "ai_prompt_hash": self._hash_prompt(current_user_prompt),
            "ai_run_id": str(uuid.uuid4()),
            "ai_job_id": str(prepared.job_id),
            "ai_selected_tier": prepared.policy.selected_model_tier,
            "ai_policy": self._policy_payload(prepared.policy),
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

    @staticmethod
    def _policy_payload(policy) -> dict:
        return {
            "task_type": policy.task_type,
            "ambiguity_level": policy.ambiguity_level,
            "risk_level": policy.risk_level,
            "max_model_tier": policy.max_model_tier,
            "max_retries": policy.max_retries,
            "max_context_tokens": policy.max_context_tokens,
            "budget_cents": policy.budget_cents,
            "requires_human_review": policy.requires_human_review,
        }
