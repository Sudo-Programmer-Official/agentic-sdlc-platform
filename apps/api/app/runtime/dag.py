from __future__ import annotations

import logging
import uuid
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkItem, WorkItemEdge
from app.services.runtime_lineage import link_run_to_work_item

log = logging.getLogger("app.runtime")


def _task_payload_from_summary(run_summary: dict | None) -> dict[str, str]:
    if not isinstance(run_summary, dict):
        return {}
    task_id = run_summary.get("task_id")
    task_title = (run_summary.get("task_title") or "").strip()
    if not task_id or not task_title:
        return {}
    payload = {
        "task_id": str(task_id),
        "source_task_id": str(task_id),
        "task_title": task_title,
        "goal": str(run_summary.get("goal") or task_title),
    }
    description = (run_summary.get("task_description") or "").strip()
    if description:
        payload["task_description"] = description
    source = (run_summary.get("task_source") or "").strip()
    if source:
        payload["task_source"] = source
    return payload


def _payload_for_stage(stage_name: str, task_payload: dict[str, str]) -> dict:
    if not task_payload:
        return {}

    task_title = task_payload["task_title"]
    stage_titles = {
        "PLAN_DAG": task_title,
        "CODE_BACKEND": f"Implement backend for {task_title}",
        "CODE_FRONTEND": f"Implement frontend for {task_title}",
        "WRITE_TESTS": f"Add tests for {task_title}",
        "REVIEW_DIFF": f"Review changes for {task_title}",
        "RUN_TESTS": f"Validate {task_title}",
        "REVIEW_INTEGRATION": f"Confirm integration for {task_title}",
    }
    payload = dict(task_payload)
    payload["title"] = stage_titles.get(stage_name, task_title)
    return payload


async def generate_template_dag(
    session: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    executor: str = "dummy",
    tenant_id: uuid.UUID | None = None,
    run_summary: dict | None = None,
) -> int:
    """Generate a small deterministic DAG for the run if none exists."""
    from sqlalchemy import select

    count = await session.scalar(select(WorkItem.id).where(WorkItem.run_id == run_id).limit(1))
    if count:
        return 0

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
    task_payload = _task_payload_from_summary(run_summary)

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
            payload=_payload_for_stage(stage_name, task_payload),
        )
        session.add(wi)
        created.append(wi)
    await session.flush()
    for wi in created:
        await link_run_to_work_item(session, wi)

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
    log.info(
        "Generated work DAG run_id=%s project_id=%s task_id=%s work_item_count=%s",
        run_id,
        project_id,
        task_payload.get("task_id"),
        len(created),
    )
    return len(created)
