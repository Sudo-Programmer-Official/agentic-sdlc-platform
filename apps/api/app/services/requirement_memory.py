from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RequirementMemory
from app.services.requirement_execution_graph import build_requirement_execution_graph
from app.services.requirement_intelligence import derive_requirement_intelligence


def _truncate(value: str, limit: int = 220) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def _unique_nonempty(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


async def compress_requirement_memory(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    requirement_id: str,
) -> RequirementMemory:
    graph = await build_requirement_execution_graph(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        requirement_id=requirement_id,
    )
    intelligence = derive_requirement_intelligence(
        requirement_updated_at=None,
        tasks=graph["tasks"],
        runs=graph["runs"],
        improvements=graph["improvements"],
        related_files=graph["related_files"],
        related_modules=graph["related_modules"],
    )

    successful_runs = [run for run in graph["runs"] if str(getattr(run, "status", "")).upper() == "COMPLETED"]
    prior_successful_fixes = []
    for run in successful_runs[:8]:
        summary = getattr(run, "summary", None) if isinstance(getattr(run, "summary", None), dict) else {}
        prior_successful_fixes.append(
            {
                "run_id": str(run.id),
                "goal": _truncate(str(summary.get("goal") or summary.get("strategy_goal") or "")),
                "files": [path for path in (summary.get("changed_files") or []) if isinstance(path, str)][:8],
                "pr_url": summary.get("pull_request_url"),
            }
        )

    recurring_failures = _unique_nonempty(intelligence["recurring_failure_patterns"])
    validation_patterns = _unique_nonempty(
        [
            str(pattern)
            for pattern in intelligence["recurring_failure_patterns"]
            if any(token in str(pattern).lower() for token in ("test", "validation", "lint", "assert"))
        ]
    )
    architectural_constraints = _unique_nonempty(
        [
            "Respect project contract protected zones."
            if intelligence["most_impacted_modules"]
            else "",
            "Keep patch scope narrow for high-risk requirements." if intelligence["risk_level"] == "HIGH" else "",
        ]
    )
    historical_patterns = _unique_nonempty(
        [
            f"Retries observed: {intelligence['retry_count']}",
            f"Unresolved improvements: {intelligence['unresolved_count']}",
            f"Most impacted modules: {', '.join(intelligence['most_impacted_modules']) or 'none'}",
            f"Frequent files: {', '.join(intelligence['frequently_modified_files']) or 'none'}",
        ]
    )
    compact_summary = _truncate(
        " | ".join(
            [
                f"Requirement {requirement_id}",
                f"risk={intelligence['risk_level']}",
                f"health={intelligence['health_score']}",
                f"retries={intelligence['retry_count']}",
                f"unresolved={intelligence['unresolved_count']}",
                f"modules={', '.join(intelligence['most_impacted_modules']) or 'none'}",
            ]
        ),
        limit=512,
    )

    existing = await session.scalar(
        select(RequirementMemory).where(
            RequirementMemory.tenant_id == tenant_id,
            RequirementMemory.project_id == project_id,
            RequirementMemory.requirement_id == requirement_id,
        )
    )
    if existing is None:
        existing = RequirementMemory(
            tenant_id=tenant_id,
            project_id=project_id,
            requirement_id=requirement_id,
        )
        session.add(existing)

    existing.compact_summary = compact_summary
    existing.historical_patterns = historical_patterns
    existing.prior_successful_fixes = prior_successful_fixes
    existing.recurring_failures = recurring_failures
    existing.architectural_constraints = architectural_constraints
    existing.validation_patterns = validation_patterns
    existing.snapshot = {
        "intelligence": intelligence,
        "counts": {
            "tasks": len(graph["tasks"]),
            "runs": len(graph["runs"]),
            "improvements": len(graph["improvements"]),
            "artifacts": len(graph["artifacts"]),
        },
    }
    await session.flush()
    return existing


def build_requirement_context_pack(memory: RequirementMemory | None) -> dict[str, Any]:
    if memory is None:
        return {}
    return {
        "requirement_id": memory.requirement_id,
        "summary": memory.compact_summary,
        "historical_patterns": list(memory.historical_patterns or [])[:8],
        "prior_successful_fixes": list(memory.prior_successful_fixes or [])[:5],
        "recurring_failures": list(memory.recurring_failures or [])[:8],
        "architectural_constraints": list(memory.architectural_constraints or [])[:8],
        "validation_patterns": list(memory.validation_patterns or [])[:8],
        "snapshot": memory.snapshot if isinstance(memory.snapshot, dict) else {},
    }
