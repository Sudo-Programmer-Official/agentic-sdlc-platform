from __future__ import annotations

from typing import Protocol, TypedDict, Literal

from app.db.models import WorkItem
from .context import RunContext


class TaskResult(TypedDict):
    status: Literal["DONE", "FAILED", "SKIPPED"]
    message: str
    payload: dict


class TaskExecutor(Protocol):
    name: str

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        ...
