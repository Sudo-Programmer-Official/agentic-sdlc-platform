from __future__ import annotations

import logging
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError, OperationalError

from app.db.models import Agent, Run, WorkItem, WorkItemEdge
from app.runtime.executor import TaskExecutor
from app.runtime.registry import build_executor, get_executor
from app.runtime.leases import reclaim_expired_work_items
from app.services.event_log import record_event
from app.services.run_resume import capture_run_checkpoint, sync_run_resume_state
from app.services.runtime_lineage import persist_work_item_artifacts
from app.services.state_guard import update_work_item_status
from app.runtime.recovery_policy import maybe_apply_recovery
from app.runtime.execution_contract import sync_run_execution_contract_state
from app.runtime.dag import TaskScopeError, generate_template_dag
from app.runtime.plan_snapshot import persist_run_plan_snapshot
from app.core.config import get_settings
from app.services.run_delivery import publish_run_branch_if_ready
from app.services.task_decomposition import persist_run_task_decomposition
from app.services.work_item_state import is_blocking_failure, is_dependency_satisfied
from app.services.workspace_supervisor import build_run_context, ensure_run_workspace

log = logging.getLogger("app.runtime.orchestrator")
_ORCHESTRATOR_MAX_DEGRADED_SLEEP_SECONDS = 8.0


def _work_item_terminal_event_type(status: str) -> str:
    if status == "DONE":
        return "WORK_ITEM_DONE"
    if status == "SKIPPED":
        return "WORK_ITEM_SKIPPED"
    return "WORK_ITEM_FAILED"


def _extract_failed_result_error(result: dict) -> str:
    payload = result.get("payload")
    message = result.get("message")
    if isinstance(payload, dict):
        for key in ("error", "last_error", "exception", "failure_reason", "reason", "details"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "executor returned FAILED without error details"


def _is_transient_orchestrator_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, OperationalError)):
        return True
    if isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False)):
        return True
    text = str(exc).lower()
    markers = ("timeout", "timed out", "connection reset", "connection refused", "temporarily unavailable")
    return any(marker in text for marker in markers)


def _orchestrator_backoff_seconds(streak: int) -> float:
    exp = max(0, min(streak - 1, 10))
    return min(_ORCHESTRATOR_MAX_DEGRADED_SLEEP_SECONDS, float(2**exp))


class RunOrchestrator:
    """Drives a run end-to-end using a provided executor."""

    def __init__(self, session_factory: Callable[[], AsyncSession], executor: TaskExecutor | None = None, executor_name: str = "dummy"):
        self.session_factory = session_factory
        self.executor = executor or get_executor(executor_name)
        self.settings = get_settings()

    async def bootstrap(
        self,
        run_id: uuid.UUID,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
        executor_name: str | None = None,
    ) -> bool:
        async with self.session_factory() as session:
            return await self.bootstrap_in_session(
                session,
                run_id,
                actor_type=actor_type,
                actor_id=actor_id,
                executor_name=executor_name,
            )

    async def _fail_run_for_workspace_error(
        self,
        session: AsyncSession,
        *,
        run: Run,
        actor_type: str,
        actor_id: str | None,
    ) -> None:
        previous = run.status
        target_status = "COMPLETED" if self.settings.runtime_never_fail_runs else "FAILED"
        run.status = target_status
        run.finished_at = run.finished_at or datetime.now(timezone.utc)
        if self.settings.runtime_never_fail_runs:
            summary = dict(run.summary or {})
            summary["degraded_completion"] = True
            summary["degraded_reason"] = "workspace_prepare_failed"
            summary["workspace_error"] = run.workspace_error
            run.summary = summary
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_DEGRADED" if self.settings.runtime_never_fail_runs else "RUN_FAILED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=run.tenant_id,
            payload={
                "previous": previous,
                "new": target_status,
                "workspace_status": run.workspace_status,
                "workspace_error": run.workspace_error,
            },
        )
        if self.settings.runtime_never_fail_runs:
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_COMPLETED",
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=run.tenant_id,
                payload={"final_status": "COMPLETED", "degraded": True, "reason": "workspace_prepare_failed"},
            )
        log.warning(
            "Run bootstrap failed due to workspace preparation error run_id=%s project_id=%s executor=%s workspace_status=%s workspace_error=%s",
            run.id,
            run.project_id,
            run.executor,
            run.workspace_status,
            run.workspace_error,
        )

    async def _fail_run_for_bootstrap_error(
        self,
        session: AsyncSession,
        *,
        run: Run,
        actor_type: str,
        actor_id: str | None,
        message: str,
    ) -> None:
        previous = run.status
        target_status = "COMPLETED" if self.settings.runtime_never_fail_runs else "FAILED"
        run.status = target_status
        run.finished_at = run.finished_at or datetime.now(timezone.utc)
        summary = dict(run.summary or {})
        summary["bootstrap_error"] = message
        if self.settings.runtime_never_fail_runs:
            summary["degraded_completion"] = True
            summary["degraded_reason"] = "bootstrap_error"
        run.summary = summary
        session.add(run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_DEGRADED" if self.settings.runtime_never_fail_runs else "RUN_FAILED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=run.tenant_id,
            payload={
                "previous": previous,
                "new": target_status,
                "reason": "bootstrap_error",
                "error": message,
            },
        )
        if self.settings.runtime_never_fail_runs:
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_COMPLETED",
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=run.tenant_id,
                payload={"final_status": "COMPLETED", "degraded": True, "reason": "bootstrap_error"},
            )
        log.warning(
            "Run bootstrap failed run_id=%s project_id=%s executor=%s error=%s",
            run.id,
            run.project_id,
            run.executor,
            message,
        )

    async def bootstrap_in_session(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
        executor_name: str | None = None,
    ) -> bool:
        if executor_name:
            self.executor = get_executor(executor_name)

        run = await self._load_run_for_update(session, run_id)
        if run is None or run.status in {"COMPLETED", "FAILED", "CANCELED"}:
            return False

        require_repo = run.executor in {"codex", "test"}

        if run.status == "QUEUED":
            await ensure_run_workspace(session, run, require_repo=require_repo)
            if run.workspace_status == "ERROR":
                await self._fail_run_for_workspace_error(
                    session,
                    run=run,
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
                await session.commit()
                return False
            now = datetime.now(timezone.utc)
            previous = run.status
            run.status = "RUNNING"
            run.started_at = run.started_at or now
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
        else:
            await ensure_run_workspace(session, run, require_repo=require_repo)
            if run.workspace_status == "ERROR":
                await self._fail_run_for_workspace_error(
                    session,
                    run=run,
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
                await session.commit()
                return False
            await session.commit()

        existing_work_item_id = await session.scalar(select(WorkItem.id).where(WorkItem.run_id == run_id).limit(1))
        if existing_work_item_id:
            return True

        run = await session.get(Run, run_id)
        if run is None:
            return False

        log.info("Run bootstrap started run_id=%s project_id=%s executor=%s", run.id, run.project_id, self.executor.name)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_BOOTSTRAP_STARTED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=run.tenant_id,
            payload={"executor": self.executor.name, "status": run.status},
        )
        await session.flush()

        selected_task_id = None
        if isinstance(run.summary, dict):
            selected_task_id = run.summary.get("task_id")
        try:
            work_item_count = await generate_template_dag(
                session,
                project_id=run.project_id,
                run_id=run_id,
                executor=self.executor.name,
                tenant_id=run.tenant_id,
                run_summary=run.summary,
            )
        except TaskScopeError as exc:
            await self._fail_run_for_bootstrap_error(
                session,
                run=run,
                actor_type=actor_type,
                actor_id=actor_id,
                message=str(exc),
            )
            await session.commit()
            return False
        snapshot = await persist_run_plan_snapshot(session, run)
        await sync_run_execution_contract_state(session, run)
        decomposition = await persist_run_task_decomposition(session, run)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="WORK_DAG_CREATED",
            actor_type=actor_type,
            tenant_id=run.tenant_id,
            task_id=uuid.UUID(str(selected_task_id)) if selected_task_id else None,
            payload={"work_item_count": work_item_count, "task_id": selected_task_id},
        )
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_PLAN_CAPTURED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=run.tenant_id,
            task_id=uuid.UUID(str(selected_task_id)) if selected_task_id else None,
            payload={
                "task_id": selected_task_id,
                "goal": snapshot.get("goal"),
                "step_count": len(snapshot.get("steps", [])),
                "validation_steps": snapshot.get("validation_steps", []),
            },
        )
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            event_type="RUN_TASK_DECOMPOSED",
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=run.tenant_id,
            task_id=uuid.UUID(str(selected_task_id)) if selected_task_id else None,
            payload={
                "task_id": selected_task_id,
                "goal": decomposition.get("goal"),
                "template_key": decomposition.get("template_key"),
                "subtask_count": len(decomposition.get("subtasks", [])),
                "risk_level": decomposition.get("risk_level"),
            },
        )
        log.info(
            "Run bootstrap seeded work items run_id=%s project_id=%s work_item_count=%s executor=%s",
            run.id,
            run.project_id,
            work_item_count,
            self.executor.name,
        )
        await session.commit()
        return True

    async def start(self, run_id: uuid.UUID, actor_type: str = "SYSTEM", actor_id: str | None = None, executor_name: str | None = None) -> None:
        bootstrapped = await self.bootstrap(
            run_id,
            actor_type=actor_type,
            actor_id=actor_id,
            executor_name=executor_name,
        )
        if not bootstrapped:
            return

        # Step 3: scheduler loop
        max_conc = max(1, self.settings.max_workitem_concurrency)
        run_failed = False
        transient_error_streak = 0

        async with self.session_factory() as session:
            use_external_runtime = await self._should_use_external_runtime(session, run_id, actor_type, actor_id)
            run = await session.get(Run, run_id)
            if run is None:
                return
            effective_mode = "external" if use_external_runtime else "embedded"
            log.info(
                "Run execution handoff run_id=%s project_id=%s requested_mode=%s effective_mode=%s",
                run.id,
                run.project_id,
                self.settings.runtime_mode,
                effective_mode,
            )
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                event_type="RUN_EXECUTION_HANDOFF",
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=run.tenant_id,
                payload={
                    "requested_mode": self.settings.runtime_mode,
                    "effective_mode": effective_mode,
                },
            )
            await session.commit()
            while True:
                try:
                    await session.commit()
                    # refresh run status
                    run = await session.get(Run, run_id)
                    if not run:
                        return
                    if run.status in {"COMPLETED", "FAILED", "CANCELED"}:
                        break

                    if await reclaim_expired_work_items(session, run_id=run_id):
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
                            select(WorkItem).where(
                                WorkItem.run_id == run_id,
                                WorkItem.status == "FAILED",
                            )
                        )
                    ).scalars().all()
                    failed_count = sum(1 for item in failed_items if is_blocking_failure(item))

                    if failed_count == 0 and queued_count == 0 and active_count == 0:
                        if use_external_runtime:
                            await asyncio.sleep(0.2)
                            continue
                        break

                    # find runnable items (QUEUED and deps done/skipped)
                    runnable: list[WorkItem] = []
                    if queued_count:
                        runnable = await self._runnable_queued_items(session, run_id=run_id, limit=max_conc)

                    if failed_count and active_count == 0 and not use_external_runtime:
                        if queued_count == 0:
                            run_failed = True
                            break
                        if not runnable:
                            await self._cancel_terminally_blocked_items(
                                session,
                                run=run,
                                actor_type=actor_type,
                                actor_id=actor_id,
                            )
                            run_failed = True
                            break

                    if use_external_runtime:
                        # external mode: do not execute items here, just wait for workers
                        await asyncio.sleep(0.2)
                        continue

                    if not runnable:
                        await asyncio.sleep(0.2)
                        continue

                    for wi in runnable:
                        await self._process_work_item(session, wi, run)
                    transient_error_streak = 0
                except Exception as exc:
                    if _is_transient_orchestrator_error(exc):
                        transient_error_streak += 1
                        sleep_for = _orchestrator_backoff_seconds(transient_error_streak)
                        log.warning(
                            "Run orchestration transient failure run_id=%s streak=%s backoff_seconds=%.1f error=%s",
                            run_id,
                            transient_error_streak,
                            sleep_for,
                            exc,
                        )
                        await asyncio.sleep(sleep_for)
                        continue
                    raise

            if use_external_runtime:
                return

            # finalize run
            final_status = (
                "COMPLETED"
                if run_failed and self.settings.runtime_never_fail_runs
                else ("FAILED" if run_failed else ("CANCELED" if run.status == "CANCELED" else "COMPLETED"))
            )
            now = datetime.now(timezone.utc)
            updated = await session.execute(
                select(Run).where(Run.id == run_id, Run.status.notin_(["COMPLETED", "FAILED", "CANCELED"])).with_for_update()
            )
            locked = updated.scalar_one_or_none()
            if locked:
                if final_status == "COMPLETED" and self.settings.run_auto_push_branch_on_completion:
                    try:
                        await publish_run_branch_if_ready(
                            session,
                            run=locked,
                            actor_type=actor_type,
                            actor_id=actor_id,
                        )
                    except Exception as exc:
                        summary = dict(locked.summary or {})
                        summary["remote_branch_push_error"] = str(exc)
                        summary["remote_branch_pushed"] = False
                        summary["delivery_manual_push_required"] = True
                        locked.summary = summary
                        await record_event(
                            session,
                            project_id=locked.project_id,
                            run_id=locked.id,
                            event_type="RUN_BRANCH_PUSH_FAILED",
                            actor_type=actor_type,
                            actor_id=actor_id,
                            tenant_id=locked.tenant_id,
                            message=str(exc),
                            payload={
                                "branch_name": locked.branch_name,
                                "workspace_status": locked.workspace_status,
                                "manual_push_required": True,
                            },
                        )
                locked.status = final_status
                locked.finished_at = now
                if run_failed and self.settings.runtime_never_fail_runs:
                    summary = dict(locked.summary or {})
                    summary["degraded_completion"] = True
                    summary["degraded_reason"] = "embedded_terminal_work_item_failure"
                    locked.summary = summary
                    await record_event(
                        session,
                        project_id=locked.project_id,
                        run_id=locked.id,
                        event_type="RUN_DEGRADED",
                        actor_type=actor_type,
                        actor_id=actor_id,
                        tenant_id=locked.tenant_id,
                        payload={"reason": "embedded_terminal_work_item_failure", "final_status": "COMPLETED"},
                    )
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

    async def _cancel_terminally_blocked_items(
        self,
        session: AsyncSession,
        *,
        run: Run,
        actor_type: str,
        actor_id: str | None,
    ) -> None:
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
            return

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
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=run.tenant_id,
                message="Canceled because an upstream failure left this work item blocked.",
                payload={
                    "work_item_id": str(wi.id),
                    "reason": "blocked_by_terminal_failure",
                },
            )
        await session.flush()

    async def _load_run_for_update(self, session: AsyncSession, run_id: uuid.UUID) -> Run | None:
        result = await session.execute(select(Run).where(Run.id == run_id).with_for_update())
        return result.scalar_one_or_none()

    async def _runnable_queued_items(
        self,
        session: AsyncSession,
        *,
        run_id: uuid.UUID,
        limit: int,
    ) -> list[WorkItem]:
        queued_items = (
            await session.execute(
                select(WorkItem)
                .where(WorkItem.run_id == run_id, WorkItem.status == "QUEUED")
                .order_by(WorkItem.priority.desc(), WorkItem.created_at)
                .limit(max(limit, 1))
            )
        ).scalars().all()
        if not queued_items:
            return []
        queued_ids = [item.id for item in queued_items]
        parent = WorkItem
        dependency_rows = (
            await session.execute(
                select(
                    WorkItemEdge.to_work_item_id,
                    parent.status,
                    parent.payload,
                    parent.result,
                )
                .join(parent, parent.id == WorkItemEdge.from_work_item_id)
                .where(
                    WorkItemEdge.run_id == run_id,
                    WorkItemEdge.to_work_item_id.in_(queued_ids),
                )
            )
        ).all()
        deps_by_child: dict = {}
        for to_work_item_id, status, payload, result_payload in dependency_rows:
            deps_by_child.setdefault(to_work_item_id, []).append(
                SimpleNamespace(status=status, payload=payload, result=result_payload)
            )
        return [
            item
            for item in queued_items
            if all(is_dependency_satisfied(dep) for dep in deps_by_child.get(item.id, []))
        ]

    async def _process_work_item(
        self,
        session: AsyncSession,
        wi: WorkItem,
        run: Run,
    ) -> None:
        work_item_id = wi.id
        run_id = run.id
        project_id = run.project_id
        tenant_id = run.tenant_id
        failure_stage = "startup"
        try:
            now = datetime.now(timezone.utc)
            wi.status = "RUNNING"
            wi.started_at = now
            wi.last_error = None
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

            failure_stage = "workspace_context"
            context = await build_run_context(session, run, require_repo=wi.executor in {"codex", "test"})
            executor = build_executor(wi.executor, repo_root=None if not context.repo_path else Path(context.repo_path))
            failure_stage = "executor_execute"
            result = await executor.execute(wi, context)
            wi.status = result.get("status", "DONE")
            wi.result = result.get("payload", {})
            wi.finished_at = datetime.now(timezone.utc)
            if wi.status == "FAILED":
                wi.last_error = _extract_failed_result_error(result)
            else:
                wi.last_error = None
            failure_stage = "artifact_persistence"
            await persist_work_item_artifacts(session, wi, (wi.result or {}).get("artifacts"))
            if wi.status in {"DONE", "SKIPPED"}:
                await capture_run_checkpoint(session, run, work_item=wi, checkpoint_kind="safe")
            failure_stage = "event_recording"
            await record_event(
                session,
                project_id=run.project_id,
                run_id=run.id,
                work_item_id=wi.id,
                event_type=_work_item_terminal_event_type(wi.status),
                actor_type="SYSTEM",
                payload={
                    "work_item_id": str(wi.id),
                    "status": wi.status,
                    "message": result.get("message"),
                    "error": wi.last_error if wi.status == "FAILED" else None,
                    "failure_stage": "executor_execute" if wi.status == "FAILED" else None,
                    "mutation_strategy": (wi.result or {}).get("mutation_strategy"),
                    "selected_strategy": ((wi.result or {}).get("mutation_strategy") or {}).get("selected"),
                    "effective_strategy": ((wi.result or {}).get("mutation_strategy") or {}).get("effective"),
                    "transition_reason": ((wi.result or {}).get("mutation_strategy") or {}).get("strategy_transition_reason"),
                    "drift_risk_score": ((wi.result or {}).get("mutation_strategy") or {}).get("drift_risk_score"),
                    "execution_zone": ((wi.result or {}).get("mutation_strategy") or {}).get("execution_zone"),
                },
            )
            session.add(wi)
            await session.flush()
            failure_stage = "recovery_policy"
            await maybe_apply_recovery(session, wi)
            await sync_run_execution_contract_state(session, run)
            await sync_run_resume_state(session, run)
        except Exception as exc:
            log.exception(
                "Work item execution failed run_id=%s work_item_id=%s type=%s stage=%s error=%s",
                run_id,
                work_item_id,
                wi.type,
                failure_stage,
                exc,
            )
            await session.rollback()
            failed_item = await session.get(WorkItem, work_item_id)
            if failed_item is None:
                return
            failed_item.status = "FAILED"
            failed_item.last_error = str(exc)
            failed_item.finished_at = datetime.now(timezone.utc)
            session.add(failed_item)
            await record_event(
                session,
                project_id=project_id,
                run_id=run_id,
                work_item_id=work_item_id,
                event_type="WORK_ITEM_FAILED",
                actor_type="SYSTEM",
                tenant_id=tenant_id,
                payload={
                    "error": str(exc),
                    "exception_class": exc.__class__.__name__,
                    "failure_stage": failure_stage,
                    "work_item_id": str(work_item_id),
                },
            )
            await session.flush()
            await maybe_apply_recovery(session, failed_item)
            refreshed_run = await session.get(Run, run_id)
            if refreshed_run is not None:
                await sync_run_execution_contract_state(session, refreshed_run)
                await sync_run_resume_state(session, refreshed_run, failed_work_item=failed_item)
