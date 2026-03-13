from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Run, RunSummary
from app.schemas.run_strategy import (
    RunStrategyCandidate,
    RunStrategyGroupResponse,
    RunStrategyPlanRequest,
    RunStrategyRecommendation,
)
from app.services.run_replay import fork_run
from app.services.run_summary_builder import ensure_project_run_summaries
from app.services.strategy_planner import plan_run_strategies


def _summary_text(run: Run, key: str) -> str | None:
    summary = run.summary or {}
    value = summary.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strategy_group_id(run: Run) -> uuid.UUID | None:
    value = (run.summary or {}).get("strategy_group_id")
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _strategy_source_run_id(run: Run) -> uuid.UUID | None:
    value = (run.summary or {}).get("strategy_source_run_id")
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _strategy_meta(run: Run, key: str) -> str | None:
    value = (run.summary or {}).get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strategy_branch_name(source_run: Run, strategy_type: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    base = (source_run.branch_name or f"run/{str(source_run.id)[:8]}").rstrip("/")
    suffix = strategy_type.replace("_", "-")
    return f"{base}-{suffix}"


def _score_run_summary(summary: RunSummary) -> tuple[float, dict[str, float], list[str]]:
    score = 0.0
    breakdown: dict[str, float] = {}
    rationale: list[str] = []

    if summary.status == "COMPLETED":
        breakdown["completed"] = 100.0
        rationale.append("Run completed successfully.")
    elif summary.status == "RUNNING":
        breakdown["running"] = 15.0
    elif summary.status == "QUEUED":
        breakdown["queued"] = 5.0
    elif summary.status == "FAILED":
        breakdown["failed"] = -60.0
        rationale.append("Run failed.")
    elif summary.status == "CANCELED":
        breakdown["canceled"] = -70.0
        rationale.append("Run was canceled.")

    if summary.pr_created:
        breakdown["pr_created"] = 20.0
        rationale.append("Run produced a PR-ready result.")

    if summary.approval_status == "APPROVED":
        breakdown["approved"] = 8.0
        rationale.append("Artifacts were approved.")
    elif summary.approval_status == "REJECTED":
        breakdown["rejected"] = -15.0
        rationale.append("Artifacts were rejected.")

    if summary.recovery_count:
        penalty = round(summary.recovery_count * 4.0, 3)
        breakdown["recovery_penalty"] = -penalty
        rationale.append(f"Needed {summary.recovery_count} recovery step{'s' if summary.recovery_count != 1 else ''}.")

    file_count = len(summary.changed_files or [])
    if file_count:
        penalty = round(min(file_count, 20) * 0.75, 3)
        breakdown["file_penalty"] = -penalty
        rationale.append(f"Changed {file_count} file{'s' if file_count != 1 else ''}.")

    if summary.elapsed_seconds:
        minutes = summary.elapsed_seconds / 60.0
        penalty = round(min(minutes, 30.0), 3)
        breakdown["time_penalty"] = -penalty
        rationale.append(f"Elapsed time was {round(summary.elapsed_seconds, 1)} seconds.")

    score = round(sum(breakdown.values()), 3)
    return score, breakdown, rationale


async def _project_runs(session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> list[Run]:
    return (
        await session.execute(
            select(Run)
            .where(Run.project_id == project_id, Run.tenant_id == tenant_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
        )
    ).scalars().all()


async def _resolve_group(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    anchor_run: Run,
) -> tuple[uuid.UUID | None, uuid.UUID, list[Run]]:
    runs = await _project_runs(session, tenant_id=tenant_id, project_id=anchor_run.project_id)
    group_id = _strategy_group_id(anchor_run)
    source_run_id = _strategy_source_run_id(anchor_run) or anchor_run.id

    if group_id is None:
        group_candidates = [
            run for run in runs if _strategy_source_run_id(run) == anchor_run.id and _strategy_group_id(run) is not None
        ]
        if group_candidates:
            group_id = _strategy_group_id(group_candidates[0])
            source_run_id = anchor_run.id
            return group_id, source_run_id, group_candidates
        return None, source_run_id, []

    group_runs = [run for run in runs if _strategy_group_id(run) == group_id]
    return group_id, source_run_id, group_runs


async def get_strategy_group(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
) -> RunStrategyGroupResponse:
    anchor_run = await session.scalar(select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id))
    if anchor_run is None:
        raise ValueError("Run not found")

    group_id, source_run_id, group_runs = await _resolve_group(session, tenant_id=tenant_id, anchor_run=anchor_run)
    if group_id is None:
        raise ValueError("No strategy group found for this run")

    project = await session.scalar(
        select(Project).where(Project.id == anchor_run.project_id, Project.tenant_id == tenant_id)
    )
    if project is None:
        raise ValueError("Project not found")

    summary_rows = await ensure_project_run_summaries(
        session,
        tenant_id=tenant_id,
        project_id=project.id,
        limit=max(25, len(group_runs) + 10),
    )
    summaries = {row.run_id: row for row in summary_rows}

    candidates: list[RunStrategyCandidate] = []
    recommended: RunStrategyRecommendation | None = None
    best_score: float | None = None
    for run in group_runs:
        summary = summaries.get(run.id)
        score: float | None = None
        breakdown: dict[str, float] = {}
        rationale: list[str] = []
        if summary is not None:
            score, breakdown, rationale = _score_run_summary(summary)
        candidate = RunStrategyCandidate(
            run_id=run.id,
            status=run.status,
            executor=run.executor,
            branch_name=run.branch_name,
            strategy_type=_strategy_meta(run, "strategy_type") or "candidate",
            label=_strategy_meta(run, "strategy_label") or "Candidate",
            rationale=_strategy_meta(run, "strategy_rationale") or "Strategy metadata not available.",
            prompt_hint=_strategy_meta(run, "strategy_prompt_hint"),
            score=score,
            score_breakdown=breakdown,
            pull_request_url=(summary.pr_url if summary is not None else _summary_text(run, "pull_request_url")),
            created_at=run.created_at,
        )
        candidates.append(candidate)

        if summary is None:
            continue
        if summary.status not in {"COMPLETED", "RUNNING", "QUEUED"}:
            continue
        if best_score is None or score > best_score:
            best_score = score
            recommendation_rationale = list(rationale)
            if summary.status == "COMPLETED" and not any("completed" in line.lower() for line in recommendation_rationale):
                recommendation_rationale.append("Completed successfully.")
            if candidate.pull_request_url and not any("pr-ready" in line.lower() for line in recommendation_rationale):
                recommendation_rationale.append("PR-ready result available.")
            recommended = RunStrategyRecommendation(
                run_id=run.id,
                strategy_type=candidate.strategy_type,
                label=candidate.label,
                score=score,
                rationale=recommendation_rationale,
            )

    source_run = await session.scalar(select(Run).where(Run.id == source_run_id, Run.tenant_id == tenant_id))
    metadata_run = source_run or anchor_run
    if group_runs:
        metadata_run = group_runs[0]
    goal = _summary_text(metadata_run, "strategy_goal") or _summary_text(source_run or anchor_run, "goal")
    error = _summary_text(metadata_run, "strategy_error")
    files = metadata_run.summary.get("strategy_files") if isinstance(metadata_run.summary, dict) else []
    if not isinstance(files, list):
        files = []

    candidates.sort(
        key=lambda item: (
            item.score if item.score is not None else float("-inf"),
            item.created_at.timestamp() if item.created_at else 0,
        ),
        reverse=True,
    )
    return RunStrategyGroupResponse(
        group_id=group_id,
        source_run_id=source_run_id,
        project_id=project.id,
        goal=goal,
        error=error,
        files=[value for value in files if isinstance(value, str)],
        candidates=candidates,
        recommendation=recommended,
    )


async def create_strategy_group(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source_run_id: uuid.UUID,
    request: RunStrategyPlanRequest,
) -> RunStrategyGroupResponse:
    source_run = await session.scalar(select(Run).where(Run.id == source_run_id, Run.tenant_id == tenant_id))
    if source_run is None:
        raise ValueError("Run not found")

    goal_text = request.goal or _summary_text(source_run, "goal") or _summary_text(source_run, "fork_notes")
    strategies = plan_run_strategies(
        goal_text=goal_text,
        error_text=request.error,
        files=request.files,
        limit=max(1, min(request.limit, 5)),
    )
    if not strategies:
        raise ValueError("No strategies available for this run")

    group_id = uuid.uuid4()
    for option in strategies:
        branch_name = _strategy_branch_name(source_run, option.strategy_type)
        await fork_run(
            session,
            source_run=source_run,
            executor=request.executor,
            branch_name=branch_name,
            start_now=request.start_now,
            summary_overrides={
                "strategy_group_id": str(group_id),
                "strategy_source_run_id": str(source_run.id),
                "strategy_type": option.strategy_type,
                "strategy_label": option.label,
                "strategy_rationale": option.rationale,
                "strategy_prompt_hint": option.prompt_hint,
                "strategy_goal": goal_text,
                "strategy_error": request.error,
                "strategy_files": request.files,
            },
        )

    return await get_strategy_group(session, tenant_id=tenant_id, run_id=source_run_id)
