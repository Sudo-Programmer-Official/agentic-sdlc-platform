from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, Run, WorkItem, WorkItemEdge
from app.runtime.executor import TaskExecutor
from app.runtime.registry import build_executor, get_executor
from app.services.event_log import record_event
from app.services.runtime_lineage import persist_work_item_artifacts
from app.services.state_guard import update_work_item_status
from app.runtime.recovery_policy import maybe_apply_recovery
from app.runtime.dag import generate_template_dag
from app.core.config import get_settings
from app.services.workspace_supervisor import build_run_context, ensure_run_workspace


class RunOrchestrator:
    """Drives a run end-to-end using a provided executor."""

    def __init__(self, session_factory: Callable[[], AsyncSession], executor: TaskExecutor | None = None, executor_name: str = "dummy"):
        self.session_factory = session_factory
        self.executor = executor or get_executor(executor_name)
        self.settings = get_settings()

    async def start(self, run_id: uuid.UUID, actor_type: str = "SYSTEM", actor_id: str | None = None, executor_name: str | None = None) -> None:
        # Step 1: transition run to RUNNING if still QUEUED
        async with self.session_factory() as session:
            run = await self._load_run_for_update(session, run_id)
            if run is None or run.status != "QUEUED":
                return
            if executor_name:
                self.executor = get_executor(executor_name)
            await ensure_run_workspace(session, run)
            now = datetime.now(timezone.utc)
            previous = run.status
            run.status = "RUNNING"
            run.started_at = now
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_RUNNING",
                actor_type=actor_type,
                actor_id=actor_id,
                payload={"previous": previous, "new": "RUNNING"},
            )
            await session.commit()

        # Step 2: ensure DAG exists
        async with self.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return
            await generate_template_dag(
                session,
                project_id=run.project_id,
                run_id=run_id,
                executor=self.executor.name,
                tenant_id=run.tenant_id,
            )
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="WORK_DAG_CREATED",
                actor_type=actor_type,
                tenant_id=run.tenant_id,
            )
            await session.commit()

        # Step 3: scheduler loop
        max_conc = max(1, self.settings.max_workitem_concurrency)
        run_failed = False

        async with self.session_factory() as session:
            use_external_runtime = await self._should_use_external_runtime(session, run_id, actor_type, actor_id)
            while True:
                await session.commit()
                # refresh run status
                run = await session.get(Run, run_id)
                if not run:
                    return
                if run.status == "CANCELED":
                    break

                # Requeue expired leases (CLAIMED items that timed out)
                now = datetime.now(timezone.utc)
                expired_items = (
                    await session.execute(
                        select(WorkItem).where(
                            WorkItem.run_id == run_id,
                            WorkItem.status == "CLAIMED",
                            WorkItem.lease_expires_at.isnot(None),
                            WorkItem.lease_expires_at < now,
                        )
                    )
                ).scalars().all()
                if expired_items:
                    for wi in expired_items:
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
                    await session.flush()

                # check completion/failed
                statuses = (
                    await session.execute(
                        select(
                            func.count().filter(WorkItem.status.in_(["RUNNING", "CLAIMED"])),
                            func.count().filter(WorkItem.status == "QUEUED"),
                        ).where(WorkItem.run_id == run_id)
                    )
                ).first()
                active_count, queued_count = statuses
                failed_items = (
                    await session.execute(
                        select(WorkItem.result).where(
                            WorkItem.run_id == run_id,
                            WorkItem.status == "FAILED",
                        )
                    )
                ).scalars().all()
                failed_count = sum(
                    1
                    for result in failed_items
                    if not (isinstance(result, dict) and result.get("superseded") is True)
                )

                if failed_count and queued_count == 0 and active_count == 0:
                    run_failed = True
                    break
                if failed_count == 0 and queued_count == 0 and active_count == 0:
                    break

                # find runnable items (QUEUED and deps done/skipped)
                from sqlalchemy.orm import aliased

                parent = aliased(WorkItem)
                blocking_exists = exists(
                    select(1)
                    .select_from(WorkItemEdge)
                    .join(parent, parent.id == WorkItemEdge.from_work_item_id)
                    .where(
                        WorkItemEdge.run_id == run_id,
                        WorkItemEdge.to_work_item_id == WorkItem.id,
                        parent.status.notin_(["DONE", "SKIPPED"]),
                    )
                )
                runnable = (
                    await session.execute(
                        select(WorkItem)
                        .where(
                            WorkItem.run_id == run_id,
                            WorkItem.status == "QUEUED",
                            ~blocking_exists,
                        )
                        .order_by(WorkItem.priority.desc(), WorkItem.created_at)
                        .limit(max_conc)
                    )
                ).scalars().all()

                if use_external_runtime:
                    # external mode: do not execute items here, just wait for workers
                    await asyncio.sleep(0.2)
                    continue

                if not runnable:
                    await asyncio.sleep(0.2)
                    continue

                for wi in runnable:
                    await self._process_work_item(session, wi, run)

            # finalize run
            final_status = "FAILED" if run_failed else ("CANCELED" if run.status == "CANCELED" else "COMPLETED")
            now = datetime.now(timezone.utc)
            updated = await session.execute(
                select(Run).where(Run.id == run_id, Run.status.notin_(["COMPLETED", "FAILED", "CANCELED"])).with_for_update()
            )
            locked = updated.scalar_one_or_none()
            if locked:
                locked.status = final_status
                locked.finished_at = now
                await record_event(
                    session,
                    project_id=locked.project_id,
                    run_id=locked.id,
                    event_type=f"RUN_{final_status}",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    payload={"final_status": final_status},
                )
                try:
                    from app.api.v1.lifecycle_score import lifecycle_score

                    await lifecycle_score(project_id=locked.project_id, session=session)
                    await record_event(
                        session,
                        project_id=locked.project_id,
                        run_id=locked.id,
                        event_type="LIFECYCLE_SCORED",
                        actor_type="SYSTEM",
                    )
                except Exception:
                    pass
            await session.commit()

    async def _should_use_external_runtime(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        actor_type: str,
        actor_id: str | None,
    ) -> bool:
        if self.settings.runtime_mode != "external":
            return False

        heartbeat_cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        worker_count = (
            await session.execute(
                select(func.count())
                .select_from(Agent)
                .where(
                    Agent.kind == "worker",
                    Agent.status == "ACTIVE",
                    Agent.last_heartbeat_at.isnot(None),
                    Agent.last_heartbeat_at >= heartbeat_cutoff,
                )
            )
        ).scalar_one()
        if worker_count:
            return True

        run = await session.get(Run, run_id)
        if run is not None:
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_RUNTIME_FALLBACK",
                actor_type=actor_type,
                actor_id=actor_id,
                payload={
                    "requested_mode": "external",
                    "effective_mode": "embedded",
                    "reason": "no_active_workers",
                },
                tenant_id=run.tenant_id,
            )
            await session.flush()
        return False

    async def _load_run_for_update(self, session: AsyncSession, run_id: uuid.UUID) -> Run | None:
        result = await session.execute(select(Run).where(Run.id == run_id).with_for_update())
        return result.scalar_one_or_none()

    async def _process_work_item(
        self,
        session: AsyncSession,
        wi: WorkItem,
        run: Run,
    ) -> None:
        try:
            now = datetime.now(timezone.utc)
            wi.status = "RUNNING"
            wi.started_at = now
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                work_item_id=wi.id,
                event_type="WORK_ITEM_STARTED",
                actor_type="SYSTEM",
                payload={"work_item_id": str(wi.id), "type": wi.type, "executor": wi.executor},
            )
            session.add(wi)
            await session.flush()

            context = await build_run_context(session, run, require_repo=wi.executor in {"codex", "test"})
            executor = build_executor(wi.executor, repo_root=None if not context.repo_path else Path(context.repo_path))
            result = await executor.execute(wi, context)
            wi.status = result.get("status", "DONE")
            wi.result = result.get("payload", {})
            wi.finished_at = datetime.now(timezone.utc)
            await persist_work_item_artifacts(session, wi, (wi.result or {}).get("artifacts"))
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                work_item_id=wi.id,
                event_type="WORK_ITEM_DONE" if wi.status == "DONE" else "WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                payload={
                    "work_item_id": str(wi.id),
                    "status": wi.status,
                    "message": result.get("message"),
                },
            )
            session.add(wi)
            await session.flush()
            await maybe_apply_recovery(session, wi)
        except Exception as exc:
            wi.status = "FAILED"
            wi.last_error = str(exc)
            wi.finished_at = datetime.now(timezone.utc)
            session.add(wi)
            await session.flush()
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                work_item_id=wi.id,
                event_type="WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                payload={"error": str(exc)},
            )
            await session.flush()
            await maybe_apply_recovery(session, wi)
