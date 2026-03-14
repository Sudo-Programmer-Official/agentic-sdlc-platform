from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models import Run, WorkItem
from app.services.event_log import record_event
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()


async def tick(session):
    settings = get_settings()
    now = datetime.now(timezone.utc)

    # Requeue expired leases (conditional)
    expired = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.status == "CLAIMED",
                WorkItem.lease_expires_at.isnot(None),
                WorkItem.lease_expires_at < now,
            )
        )
    ).scalars().all()
    for wi in expired:
        from app.services.state_guard import update_work_item_status
        ok = await update_work_item_status(
            session,
            wi.id,
            ["CLAIMED"],
            "QUEUED",
            assigned_agent_id=None,
            lease_expires_at=None,
        )
        if not ok:
            continue
        await record_event(
            session,
            project_id=wi.project_id,
            run_id=wi.run_id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_LEASE_EXPIRED",
            actor_type="SYSTEM",
            payload={"work_item_id": str(wi.id)},
        )

    # finalize runs
    runs = (
        await session.execute(
            select(Run).where(Run.status.in_(["RUNNING", "QUEUED"]))
        )
    ).scalars().all()
    from app.services.state_guard import update_run_status
    for run in runs:
        # Hard stop: reviewer rejection is terminal
        failed_review = (
            await session.execute(
                select(func.count()).where(
                    WorkItem.run_id == run.id,
                    WorkItem.type == "REVIEW_DIFF",
                    WorkItem.status == "FAILED",
                )
            )
        ).scalar() or 0
        if failed_review:
            ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "FAILED", set_finished=True)
            if ok:
                await record_event(
                    session,
                    project_id=run.project_id,
                    run_id=run.id,
                    event_type="RUN_FAILED",
                    actor_type="SYSTEM",
                    payload={"reason": "review_diff_rejected"},
                )
                try:
                    await lifecycle_score(project_id=run.project_id, session=session)
                    await record_event(
                        session,
                        project_id=run.project_id,
                        run_id=run.id,
                        event_type="LIFECYCLE_SCORED",
                        actor_type="SYSTEM",
                    )
                except Exception:
                    pass
            continue

        failed_non_superseded = (
            await session.execute(
                select(func.count()).where(
                    WorkItem.run_id == run.id,
                    WorkItem.status == "FAILED",
                    (WorkItem.result["superseded"].astext.is_(None)) | (WorkItem.result["superseded"].astext != "true"),
                )
            )
        ).scalar() or 0
        active = (
            await session.execute(
                select(func.count()).where(
                    WorkItem.run_id == run.id,
                    WorkItem.status.in_(["RUNNING", "CLAIMED"]),
                )
            )
        ).scalar() or 0
        queued = (
            await session.execute(
                select(func.count()).where(
                    WorkItem.run_id == run.id,
                    WorkItem.status == "QUEUED",
                )
            )
        ).scalar() or 0

        if failed_non_superseded and active == 0 and queued == 0:
            ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "FAILED", set_finished=True)
            if not ok:
                continue
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_FAILED",
                actor_type="SYSTEM",
            )
        elif failed_non_superseded == 0 and active == 0 and queued == 0:
            ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "COMPLETED", set_finished=True)
            if not ok:
                continue
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_COMPLETED",
                actor_type="SYSTEM",
            )
            try:
                from app.services import knowledge_service

                await knowledge_service.ingest_agent_run_event(session, run_id=run.id, actor_id="system")
            except Exception:
                pass
        else:
            continue
        try:
            await lifecycle_score(project_id=run.project_id, session=session)
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="LIFECYCLE_SCORED",
                actor_type="SYSTEM",
            )
        except Exception:
            pass


async def main():
    settings = get_settings()
    interval = 1.0
    while True:
        async with SessionLocal() as session:
            try:
                await tick(session)
                await session.commit()
            except Exception:
                await session.rollback()
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
