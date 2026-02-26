from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, exists, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Document, Task, Trace
from app.db.session import get_session

# Keep legacy /store/... routes and add public /projects/... routes to match frontend calls.
router = APIRouter(prefix="/store", tags=["health"])
public_router = APIRouter(tags=["health"])


@router.get("/projects/{project_id}/health")
@public_router.get("/projects/{project_id}/health")
async def project_health(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    orphan_tasks_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(Task.project_id == project_id, Task.document_id.is_(None), Task.deleted_at.is_(None))
            .subquery()
        )
    )

    docs_without_tasks_count = await session.scalar(
        select(func.count()).select_from(
            select(Document.id)
            .where(
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
                ~exists().where(Task.document_id == Document.id, Task.deleted_at.is_(None)),
            )
            .subquery()
        )
    )

    tasks_without_trace_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.deleted_at.is_(None),
                ~exists().where(
                    Trace.project_id == project_id,
                    Trace.to_id == Task.id,
                    Trace.to_type == "task",
                    Trace.from_type == "document",
                    Trace.deleted_at.is_(None),
                ),
            )
            .subquery()
        )
    )

    deprecated_without_supersede_count = await session.scalar(
        select(func.count()).select_from(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.status == "DEPRECATED",
                Task.deleted_at.is_(None),
                ~exists().where(
                    Trace.project_id == project_id,
                    Trace.from_id == Task.id,
                    Trace.relation_type == "supersedes",
                    Trace.deleted_at.is_(None),
                ),
            )
            .subquery()
        )
    )

    # Cycle detection
    traces = (
        await session.execute(
            select(Trace.from_id, Trace.to_id).where(
                Trace.project_id == project_id,
                Trace.deleted_at.is_(None),
            )
        )
    ).all()
    adj: dict[uuid.UUID, list[uuid.UUID]] = {}
    for f, t in traces:
        adj.setdefault(f, []).append(t)

    cycles = []
    visited: set[uuid.UUID] = set()
    stack: set[uuid.UUID] = set()

    def dfs(node: uuid.UUID, path: list[uuid.UUID]):
        if node in stack:
            try:
                idx = path.index(node)
                cycles.append(path[idx:])
            except ValueError:
                cycles.append(path + [node])
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        for nei in adj.get(node, []):
            if len(cycles) >= 3:
                break
            dfs(nei, path + [nei])
        stack.remove(node)

    for node in adj.keys():
        if len(cycles) >= 3:
            break
        dfs(node, [node])

    # longest chain length (approx via DFS depth)
    longest_chain = 0
    for node in adj.keys():
        seen = set()
        def depth(n):
            if n in seen:
                return 0
            seen.add(n)
            if not adj.get(n):
                return 1
            return 1 + max(depth(child) for child in adj.get(n, []))
        longest_chain = max(longest_chain, depth(node))

    return {
        "orphan_tasks": orphan_tasks_count > 0,
        "docs_without_tasks": docs_without_tasks_count > 0,
        "tasks_without_trace": tasks_without_trace_count > 0,
        "deprecated_without_supersede": deprecated_without_supersede_count > 0,
        "graph_cycles_detected": len(cycles) > 0,
        "counts": {
            "orphan_tasks": orphan_tasks_count,
            "docs_without_tasks": docs_without_tasks_count,
            "tasks_without_trace": tasks_without_trace_count,
            "deprecated_without_supersede": deprecated_without_supersede_count,
            "cycles": len(cycles),
            "longest_chain": longest_chain,
        },
        "sample_cycles": cycles,
    }
