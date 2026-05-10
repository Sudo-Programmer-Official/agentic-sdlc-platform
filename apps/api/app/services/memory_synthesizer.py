from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import MemorySummaryArtifact, Project
from app.db.session import SessionLocal
from app.schemas.mission_control import MissionControlMemorySummaryListResponse
from app.services.project_evolution_timeline import list_memory_summaries, materialize_timeline_summaries

log = logging.getLogger("app.memory_synthesizer")


async def synthesize_project_memory(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> MissionControlMemorySummaryListResponse:
    await materialize_timeline_summaries(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    return await list_memory_summaries(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=50,
    )


async def synthesize_project_understanding(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict:
    summaries = await list_memory_summaries(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=60,
    )
    by_type: dict[str, list[MemorySummaryArtifact]] = {}
    for item in summaries.items:
        by_type.setdefault(item.summary_type, []).append(item)

    latest = lambda k: (by_type.get(k) or [None])[0]
    daily = latest("project_evolution_daily")
    weekly = latest("project_evolution_weekly")
    milestone = latest("project_evolution_milestone")

    top_risks: list[str] = []
    if weekly and isinstance(weekly.payload, dict):
        if int(weekly.payload.get("critical_events") or 0) > 0:
            top_risks.append("Critical events detected in weekly memory window.")
        if int(weekly.payload.get("recovery_events") or 0) > 0:
            top_risks.append("Frequent recovery signals indicate unstable execution path.")

    major_requirements: list[str] = []
    unstable_validations: list[str] = []
    if milestone and isinstance(milestone.payload, dict):
        highlights = milestone.payload.get("highlights")
        if isinstance(highlights, list):
            unstable_validations = [str(v) for v in highlights[:3]]

    return {
        "project_id": str(project_id),
        "summary_artifact_count": len(summaries.items),
        "major_requirements": major_requirements,
        "top_risks": top_risks[:5],
        "unstable_validations": unstable_validations[:5],
        "latest_summaries": {
            "daily": daily.payload if daily else {},
            "weekly": weekly.payload if weekly else {},
            "milestone": milestone.payload if milestone else {},
        },
    }


async def refresh_memory_summaries_once() -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        projects = (
            await session.execute(
                select(Project).order_by(Project.updated_at.desc()).limit(max(1, settings.memory_synthesizer_project_limit))
            )
        ).scalars().all()
        for project in projects:
            try:
                await materialize_timeline_summaries(
                    session,
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                )
            except Exception:
                await session.rollback()
                log.exception("Memory synthesis failed project_id=%s", project.id)


async def run_memory_synthesizer_daemon(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(120, int(settings.memory_synthesizer_interval_seconds))
    while not stop_event.is_set():
        try:
            await refresh_memory_summaries_once()
        except Exception:
            log.exception("Memory synthesizer cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def shutdown_memory_synthesizer(task: asyncio.Task | None, stop_event: asyncio.Event | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
