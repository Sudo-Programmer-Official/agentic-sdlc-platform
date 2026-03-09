from __future__ import annotations

import uuid
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkItem, WorkItemEdge


async def generate_template_dag(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    executor: str = "dummy",
    tenant_id: uuid.UUID | None = None,
) -> None:
    """Generate a small deterministic DAG for the run if none exists."""
    from sqlalchemy import select

    count = await session.scalar(select(WorkItem.id).where(WorkItem.run_id == run_id).limit(1))
    if count:
        return

    nodes = [
        ("PLAN_DAG", "plan"),
        ("CODE_BACKEND", "code"),
        ("CODE_FRONTEND", "code"),
        ("WRITE_TESTS", "test"),
        ("REVIEW_DIFF", "review"),
        ("RUN_TESTS", "test_run"),
        ("REVIEW_INTEGRATION", "review"),
    ]
    default_caps = {
        "plan": ["plan"],
        "code": ["code"],
        "test": ["test"],
        "test_run": ["test"],
        "review": ["review"],
        "fix_test_failure": ["code"],
    }

    created: List[WorkItem] = []
    for idx, (stage_name, capability_key) in enumerate(nodes):
        exec_name = executor
        if stage_name == "RUN_TESTS" and executor not in {"dummy", "test"}:
            exec_name = "test"
        wi = WorkItem(
            project_id=project_id,
            tenant_id=tenant_id or uuid.UUID(int=0),
            run_id=run_id,
            type=stage_name,
            key=stage_name,
            priority=10 - idx,
            executor=exec_name,
            required_capabilities=default_caps.get(capability_key, []),
        )
        session.add(wi)
        created.append(wi)
    await session.flush()

    # edges
    key_to_id = {wi.key: wi.id for wi in created}
    edges: list[tuple[str, str]] = [
        ("PLAN_DAG", "CODE_BACKEND"),
        ("PLAN_DAG", "CODE_FRONTEND"),
        ("CODE_BACKEND", "WRITE_TESTS"),
        ("CODE_FRONTEND", "WRITE_TESTS"),
        ("WRITE_TESTS", "REVIEW_DIFF"),
        ("REVIEW_DIFF", "RUN_TESTS"),
        ("RUN_TESTS", "REVIEW_INTEGRATION"),
    ]
    dependents_count: dict[uuid.UUID, int] = {}
    for src, dst in edges:
        session.add(
            WorkItemEdge(
                tenant_id=tenant_id or uuid.UUID(int=0),
                run_id=run_id,
                from_work_item_id=key_to_id[src],
                to_work_item_id=key_to_id[dst],
            )
        )
        dependents_count[key_to_id[dst]] = dependents_count.get(key_to_id[dst], 0) + 1
    # Update depends_on_count
    for wi in created:
        wi.depends_on_count = dependents_count.get(wi.id, 0)
        session.add(wi)
    await session.flush()
