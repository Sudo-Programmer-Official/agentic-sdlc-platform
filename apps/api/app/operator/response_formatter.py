from __future__ import annotations

from typing import Any

from app.operator.schemas import OperatorAction, OperatorReference, OperatorResponse


def compose_answer(*, facts: list[str], suggestion: str | None = None) -> str:
    lines = ["Facts:"]
    lines.extend(f"- {fact}" for fact in facts)
    if suggestion:
        lines.extend(["", "Suggestion:", suggestion])
    return "\n".join(lines)


def build_response(
    *,
    answer: str,
    intent: str,
    references: list[OperatorReference] | None = None,
    actions: list[OperatorAction] | None = None,
    grounding_tools: list[str] | None = None,
    facts: list[str] | None = None,
    tool_results: dict[str, Any] | None = None,
    status: str = "ok",
) -> OperatorResponse:
    return OperatorResponse(
        answer=answer,
        intent=intent,
        status=status,
        references=references or [],
        actions=actions or [],
        grounding_tools=grounding_tools or [],
        facts=facts or [],
        tool_results=tool_results or {},
    )
