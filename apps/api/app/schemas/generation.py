from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class TaskGenInput(BaseModel):
    model: str = Field(
        default="router-managed",
        description="Legacy field retained for compatibility. Model selection is decided by the AI policy router.",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_tasks: int = Field(default=8, ge=1, le=50)


class GeneratedTask(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "func"
    confidence: float = 0.75


class TaskGenResponse(BaseModel):
    tasks: List[GeneratedTask]
