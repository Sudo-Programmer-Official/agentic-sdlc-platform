from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator


class OperatorContext(BaseModel):
    run_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None


class OperatorRequest(BaseModel):
    project_id: uuid.UUID
    message: str = Field(min_length=1, max_length=4000)
    context: OperatorContext = Field(default_factory=OperatorContext)
    run_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def merge_legacy_context(self) -> "OperatorRequest":
        if self.run_id and self.context.run_id is None:
            self.context.run_id = self.run_id
        if self.artifact_id and self.context.artifact_id is None:
            self.context.artifact_id = self.artifact_id
        return self


class OperatorReference(BaseModel):
    type: str
    label: str
    id: str | None = None
    path: str | None = None
    url: str | None = None
    meta: dict[str, Any] | None = None


class OperatorAction(BaseModel):
    label: str
    type: str
    target_id: str | None = None
    path: str | None = None
    url: str | None = None
    prompt: str | None = None
    meta: dict[str, Any] | None = None


class OperatorResponse(BaseModel):
    answer: str
    intent: str
    status: str = "ok"
    references: list[OperatorReference] = Field(default_factory=list)
    actions: list[OperatorAction] = Field(default_factory=list)
    grounding_tools: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    tool_results: dict[str, Any] = Field(default_factory=dict)
