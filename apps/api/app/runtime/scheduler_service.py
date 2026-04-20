from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, func, exists

from app.core.config import get_settings
from app.db.models import Run, WorkItem, WorkItemEdge
from app.db.session import SessionLocal
from app.runtime.leases import reclaim_expired_work_items
from app.services.event_log import record_event
from app.services.run_delivery import publish_run_branch_if_ready
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()


async def _cancel_terminally_blocked_items(session, run: Run) -> int:
    blocked_items = (
        await session.execute(
            select(WorkItem)
            .where(
                WorkItem.run_id == run.id,
                WorkItem.status == "QUEUED",
            )
            .order_by(WorkItem.priority.desc(), WorkItem.created_at)
        )
    ).scalars().all()
    if not blocked_items:
        return 0

    finished_at = datetime.now(timezone.utc)
    for wi in blocked_items:
        wi.status = "CANCELED"
        wi.finished_at = finished_at
        session.add(wi)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=wi.id,
            event_type="WORK_ITEM_CANCELED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            message="Canceled because an upstream failure left this work item blocked.",
            payload={
                "work_item_id": str(wi.id),
                "reason": "blocked_by_terminal_failure",
            },
        )
    await session.flush()
    return len(blocked_items)


async def tick(session):
    settings = get_settings()

    await reclaim_expired_work_items(session)

    # finalize runs
    runs = (
        await session.execute(
            select(Run).where(Run.status.in_(["RUNNING", "QUEUED"]))
        )
    ).scalars().all()
    from app.services.state_guard import update_run_status
    for run in runs:
        total_items = (
            await session.execute(
                select(func.count()).where(WorkItem.run_id == run.id)
            )
        ).scalar() or 0
        if total_items == 0:
            # Fresh runs are bootstrapped in phases: the run row can briefly exist before the DAG is seeded.
            # Do not finalize until at least one work item exists for the run.
            continue

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

        failed_results = (
            await session.execute(
                select(WorkItem.result).where(
                    WorkItem.run_id == run.id,
                    WorkItem.status == "FAILED",
                )
            )
        ).scalars().all()
        failed_non_superseded = sum(
            1
            for result in failed_results
            if not (isinstance(result, dict) and result.get("superseded") is True)
        )
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
        if failed_non_superseded and active == 0 and queued:
            from sqlalchemy.orm import aliased

            parent = aliased(WorkItem)
            blocking_exists = exists(
                select(1)
                .select_from(WorkItemEdge)
                .join(parent, parent.id == WorkItemEdge.from_work_item_id)
                .where(
                    WorkItemEdge.run_id == run.id,
                    WorkItemEdge.to_work_item_id == WorkItem.id,
                    parent.status.notin_(["DONE", "SKIPPED"]),
                )
            )
            runnable_queued = (
                await session.execute(
                    select(func.count())
                    .select_from(WorkItem)
                    .where(
                        WorkItem.run_id == run.id,
                        WorkItem.status == "QUEUED",
                        ~blocking_exists,
                    )
                )
            ).scalar() or 0
            if runnable_queued == 0:
                canceled_count = await _cancel_terminally_blocked_items(session, run)
                if canceled_count:
                    queued = 0

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
            locked = await session.scalar(
                select(Run)
                .where(Run.id == run.id, Run.status.in_(["RUNNING", "QUEUED"]))
                .with_for_update()
            )
            if locked is None:
                continue
            final_status = "COMPLETED"
            if settings.run_auto_push_branch_on_completion:
                try:
                    await publish_run_branch_if_ready(
                        session,
                        run=locked,
                        actor_type="SYSTEM",
                    )
                except Exception as exc:
                    final_status = "FAILED"
                    summary = dict(locked.summary or {})
                    summary["remote_branch_push_error"] = str(exc)
                    locked.summary = summary
                    await record_event(
                        session,
                        project_id=locked.project_id,
                        run_id=locked.id,
                        event_type="RUN_BRANCH_PUSH_FAILED",
                        actor_type="SYSTEM",
                        tenant_id=locked.tenant_id,
                        message=str(exc),
                        payload={
                            "branch_name": locked.branch_name,
                            "workspace_status": locked.workspace_status,
                        },
                    )

            locked.status = final_status
            locked.finished_at = datetime.now(timezone.utc)
            session.add(locked)
            await record_event(
                session,
                project_id=locked.project_id,
                run_id=locked.id,
                event_type=f"RUN_{final_status}",
                actor_type="SYSTEM",
            )
            if final_status == "COMPLETED":
                try:
                    from app.services import knowledge_service

                    await knowledge_service.ingest_agent_run_event(session, run_id=locked.id, actor_id="system")
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
