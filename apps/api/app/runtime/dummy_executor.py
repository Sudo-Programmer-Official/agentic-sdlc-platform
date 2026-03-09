from __future__ import annotations

import random
import asyncio

from app.db.models import WorkItem
from .executor import TaskExecutor, TaskResult
from .context import RunContext


class DummyExecutor(TaskExecutor):
    name = "dummy"

    async def execute(self, work_item: WorkItem, context: RunContext) -> TaskResult:
        # Simulate work
        await asyncio.sleep(random.uniform(0.05, 0.15))
        fail = "fail" in (work_item.key or "").lower()
        status: str = "FAILED" if fail else "DONE"
        return {
            "status": status,
            "message": "simulated execution",
            "payload": {"executor": "dummy"},
        }
