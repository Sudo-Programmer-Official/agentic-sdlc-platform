from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Project
from app.db.session import SessionLocal
from app.services.requirement_memory import compress_requirement_memory
from app.services.requirement_tracking import build_requirement_summary

log = logging.getLogger("app.requirement_refresh")


async def refresh_requirement_memory_once() -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        projects = (
            await session.execute(
                select(Project).order_by(Project.updated_at.desc()).limit(max(1, settings.requirement_memory_refresh_project_limit))
            )
        ).scalars().all()
        for project in projects:
            try:
                summary = await build_requirement_summary(
                    session,
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    limit=max(1, settings.requirement_memory_refresh_requirement_limit),
                    offset=0,
                )
                for item in summary.get("items", []):
                    req_id = str(item.get("requirement_id") or "").strip()
                    if not req_id:
                        continue
                    await compress_requirement_memory(
                        session,
                        tenant_id=project.tenant_id,
                        project_id=project.id,
                        requirement_id=req_id,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("Requirement memory refresh failed project_id=%s", project.id)


async def run_requirement_memory_daemon(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(60, int(settings.requirement_memory_refresh_interval_seconds))
    while not stop_event.is_set():
        try:
            await refresh_requirement_memory_once()
        except Exception:
            log.exception("Requirement memory daemon cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def shutdown_daemon(task: asyncio.Task | None, stop_event: asyncio.Event | None) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
