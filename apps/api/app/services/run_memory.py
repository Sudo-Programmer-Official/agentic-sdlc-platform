from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.run_memory import RunMemoryMatch, RunMemoryResponse
from app.services.run_summary_builder import ensure_project_run_summaries

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {token for token in _TOKEN_RE.findall(text.lower()) if len(token) >= 3}


async def find_similar_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    goal_text: str | None = None,
    error_text: str | None = None,
    files: list[str] | None = None,
    limit: int = 5,
) -> RunMemoryResponse:
    goal_tokens = _tokenize(goal_text)
    error_tokens = _tokenize(error_text)
    file_terms = {value.strip() for value in (files or []) if value and value.strip()}
    if not goal_tokens and not error_tokens and not file_terms:
        raise ValueError("Provide at least one of goal, error, or file")

    scan_limit = min(max(limit * 10, 25), 100)
    summaries = await ensure_project_run_summaries(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=scan_limit,
    )
    if not summaries:
        return RunMemoryResponse(query={"goal": goal_text, "error": error_text, "files": sorted(file_terms)}, matches=[])

    matches: list[RunMemoryMatch] = []
    for summary in summaries:
        run_goal_tokens = _tokenize(summary.goal_text)
        run_error_tokens = _tokenize(summary.primary_error)
        changed_files = {value for value in summary.changed_files if isinstance(value, str)}

        breakdown: dict[str, float] = {}
        if goal_tokens and run_goal_tokens:
            overlap = goal_tokens & run_goal_tokens
            if overlap:
                breakdown["goal"] = round(len(overlap) / max(len(goal_tokens), 1) * 3.0, 3)
        if error_tokens and run_error_tokens:
            overlap = error_tokens & run_error_tokens
            if overlap:
                breakdown["error"] = round(len(overlap) / max(len(error_tokens), 1) * 4.0, 3)
        if file_terms and changed_files:
            overlap_files = file_terms & changed_files
            if overlap_files:
                breakdown["files"] = float(len(overlap_files) * 2)
        if summary.status == "COMPLETED":
            breakdown["success_bias"] = 0.5

        score = round(sum(breakdown.values()), 3)
        if score <= 0:
            continue

        matches.append(
            RunMemoryMatch(
                run_id=summary.run_id,
                status=summary.status,
                executor=summary.executor,
                branch_name=summary.branch_name,
                goal=summary.goal_text,
                score=score,
                score_breakdown=breakdown,
                elapsed_seconds=summary.elapsed_seconds,
                recovery_count=summary.recovery_count,
                files_changed=sorted(changed_files),
                artifact_types=[value for value in summary.artifact_types if isinstance(value, str)],
                pull_request_url=summary.pr_url,
                last_error=summary.primary_error,
                created_at=summary.run_created_at or summary.created_at,
                finished_at=summary.finished_at,
            )
        )

    matches.sort(
        key=lambda match: (
            -match.score,
            0 if match.status == "COMPLETED" else 1,
            -(match.created_at.timestamp() if match.created_at else 0),
        )
    )
    return RunMemoryResponse(
        query={
            "goal": goal_text,
            "error": error_text,
            "files": sorted(file_terms),
            "limit": limit,
        },
        matches=matches[:limit],
    )
