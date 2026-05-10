from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact, ImprovementRequest, Run, Task


def _task_req_ids(task: Task) -> set[str]:
    out: set[str] = set()
    if task.requirement_id:
        out.add(task.requirement_id)
    if isinstance(task.derived_from_requirement_ids, list):
        out.update(str(item).strip() for item in task.derived_from_requirement_ids if str(item).strip())
    return out


def _run_req_ids(run: Run, tasks_by_run: dict[uuid.UUID, list[Task]]) -> set[str]:
    out: set[str] = set()
    summary = run.summary if isinstance(run.summary, dict) else {}
    if run.requirement_id:
        out.add(run.requirement_id)
    rid = summary.get("requirement_id")
    if isinstance(rid, str) and rid.strip():
        out.add(rid.strip())
    arr = summary.get("requirement_ids")
    if isinstance(arr, list):
        out.update(str(item).strip() for item in arr if str(item).strip())
    for task in tasks_by_run.get(run.id, []):
        out.update(_task_req_ids(task))
    return out


def _module_from_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip().strip("./")
    if "/" not in cleaned:
        return cleaned
    return cleaned.split("/", 1)[0]


async def build_requirement_execution_graph(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    requirement_id: str,
) -> dict[str, Any]:
    tasks = (
        await session.execute(
            select(Task).where(Task.tenant_id == tenant_id, Task.project_id == project_id, Task.deleted_at.is_(None))
        )
    ).scalars().all()
    linked_tasks = [task for task in tasks if requirement_id in _task_req_ids(task)]
    tasks_by_run: dict[uuid.UUID, list[Task]] = {}
    for task in tasks:
        if task.run_id:
            tasks_by_run.setdefault(task.run_id, []).append(task)

    runs = (
        await session.execute(select(Run).where(Run.tenant_id == tenant_id, Run.project_id == project_id))
    ).scalars().all()
    linked_runs = [run for run in runs if requirement_id in _run_req_ids(run, tasks_by_run)]
    run_ids = {run.id for run in linked_runs}
    task_ids = {task.id for task in linked_tasks}

    improvements = (
        await session.execute(
            select(ImprovementRequest).where(ImprovementRequest.tenant_id == tenant_id, ImprovementRequest.project_id == project_id)
        )
    ).scalars().all()
    linked_improvements = [
        item
        for item in improvements
        if item.source_requirement_id == requirement_id or item.source_run_id in run_ids
    ]

    artifacts = (
        await session.execute(
            select(Artifact).where(Artifact.tenant_id == tenant_id, Artifact.project_id == project_id, Artifact.deleted_at.is_(None))
        )
    ).scalars().all()
    linked_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.requirement_id == requirement_id or artifact.run_id in run_ids or artifact.task_id in task_ids
    ]

    pull_requests: list[dict[str, Any]] = []
    deploys: list[dict[str, Any]] = []
    related_files: list[str] = []
    for run in linked_runs:
        summary = run.summary if isinstance(run.summary, dict) else {}
        pr_url = summary.get("pull_request_url")
        if isinstance(pr_url, str) and pr_url.strip():
            pull_requests.append(
                {
                    "run_id": str(run.id),
                    "url": pr_url.strip(),
                    "number": summary.get("pull_request_number"),
                    "status": run.status,
                    "created_at": run.updated_at or run.created_at,
                }
            )
        if summary.get("remote_branch_pushed") is True:
            deploys.append(
                {
                    "run_id": str(run.id),
                    "branch": summary.get("remote_branch_name") or run.branch_name,
                    "commit": summary.get("remote_branch_commit_sha"),
                    "pushed_at": summary.get("remote_branch_pushed_at"),
                    "status": run.status,
                }
            )
        changed = summary.get("changed_files")
        if isinstance(changed, list):
            related_files.extend([item for item in changed if isinstance(item, str)])

    for artifact in linked_artifacts:
        meta = artifact.extra_metadata if isinstance(artifact.extra_metadata, dict) else {}
        files = meta.get("files_changed")
        if isinstance(files, list):
            related_files.extend([item for item in files if isinstance(item, str)])

    related_files = list(dict.fromkeys(path.strip() for path in related_files if path.strip()))
    related_modules = list(dict.fromkeys(_module_from_path(path) for path in related_files))

    return {
        "requirement_id": requirement_id,
        "tasks": linked_tasks,
        "runs": linked_runs,
        "improvements": linked_improvements,
        "artifacts": linked_artifacts,
        "pull_requests": pull_requests,
        "deploys": deploys,
        "related_files": related_files,
        "related_modules": related_modules,
    }
