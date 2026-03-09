from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, constr


class Action(BaseModel):
    type: Literal["write_file", "delete_file", "apply_patch", "note"]
    path: Optional[str] = None
    content: Optional[str] = None
    patch: Optional[str] = None
    text: Optional[str] = None


class Artifact(BaseModel):
    type: constr(min_length=1)
    content: str


class CodexPlan(BaseModel):
    status: Literal["DONE", "FAILED", "SKIPPED"]
    message: constr(min_length=1)
    warnings: List[str] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
    retryable: bool = False
    risk_score: Optional[float] = None
    confidence: Optional[float] = None
    patch_complexity: Optional[float] = None
