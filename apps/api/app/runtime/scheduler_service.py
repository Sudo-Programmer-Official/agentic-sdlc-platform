from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select, func

from app.core.config import get_settings
from app.db.models import Agent, Run, RunEvent, WorkItem, WorkItemEdge
from app.db.session import SessionLocal
from app.runtime.leases import reclaim_expired_work_items, reclaim_orphaned_work_items
from app.runtime.recovery_policy import has_pending_recovery_work, sync_run_recovery_latch
from app.services.event_log import record_event
from app.services.run_delivery import publish_run_branch_if_ready
from app.services.work_item_state import is_blocking_failure, is_dependency_satisfied, is_superseded_failure
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()

VALIDATION_TERMINAL_TYPES = {"WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"}
RUN_PROGRESS_EVENT_TYPES = {"WORK_ITEM_CLAIMED", "WORK_ITEM_DONE", "WORK_ITEM_FAILED", "WORK_ITEM_SKIPPED"}
STALL_TIMEOUT_SECONDS = 90
STALL_EVENT_THROTTLE_SECONDS = 60
STALL_RECOVERY_MAX_ATTEMPTS = 2
ACTIVE_STALL_PAUSE_SECONDS = 600
BUDGET_WARNING_EVENT_THROTTLE_SECONDS = 120
MAX_IDENTICAL_TEST_FAILURES = 3


def _is_recovery_item(item: WorkItem) -> bool:
    payload = item.payload if isinstance(item.payload, dict) else {}
    result = item.result if isinstance(item.result, dict) else {}
    return item.type == "FIX_TEST_FAILURE" or any(
        payload.get(key) for key in ("recovery_action", "recovery_source_id", "failed_work_item_id")
    ) or any(result.get(key) for key in ("recovery_action", "retry_state"))


async def _supersede_stale_failed_recoveries(session, run: Run) -> None:
    work_items = (
        await session.execute(select(WorkItem).where(WorkItem.run_id == run.id))
    ).scalars().all()
    validation_items = [
        item
        for item in work_items
        if item.type in VALIDATION_TERMINAL_TYPES and not is_superseded_failure(item)
    ]
    if not validation_items or not all(item.status in {"DONE", "SKIPPED"} for item in validation_items):
        return

    finished_at = datetime.now(timezone.utc)
    changed = False
    for item in work_items:
        if item.status != "FAILED" or not _is_recovery_item(item) or is_superseded_failure(item):
            continue
        result = dict(item.result or {})
        result["superseded"] = True
        result["superseded_reason"] = "validation_path_passed_after_recovery_failure"
        result["superseded_at"] = finished_at.isoformat()
        item.result = result
        session.add(item)
        changed = True
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=item.id,
            event_type="WORK_ITEM_SUPERSEDED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            message="Failed recovery item superseded because validation and integration passed.",
            payload={
                "work_item_id": str(item.id),
                "reason": "validation_path_passed_after_recovery_failure",
            },
        )
    if changed:
        await session.flush()


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


async def _runnable_queued_items(session, run: Run) -> list[WorkItem]:
    queued_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id, WorkItem.status == "QUEUED")
            .order_by(WorkItem.priority.desc(), WorkItem.created_at)
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
                WorkItemEdge.run_id == run.id,
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


async def _nudge_worker_if_stalled(session, run: Run, runnable_items: list[WorkItem], active_count: int) -> bool:
    if active_count > 0 or not runnable_items:
        return False
    required_caps = {cap for item in runnable_items for cap in (item.required_capabilities or [])}
    executors = {item.executor for item in runnable_items if item.executor}
    agents = (
        await session.execute(
            select(Agent)
            .where(Agent.kind == "worker", Agent.status == "ACTIVE")
            .order_by(Agent.last_heartbeat_at.desc(), Agent.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    if not agents:
        return False
    agent = None
    for candidate in agents:
        candidate_caps = set(candidate.capabilities or [])
        candidate_executors = set(candidate.executors or [])
        if required_caps and not required_caps.issubset(candidate_caps):
            continue
        if executors and candidate_executors and not (executors & candidate_executors):
            continue
        agent = candidate
        break
    if agent is None:
        return False
    from app.runtime.worker_service import tick_worker

    await tick_worker(agent.id)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_WORKER_NUDGED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "agent_id": str(agent.id),
            "runnable_queued_count": len(runnable_items),
            "reason": "stalled_runnable_queue",
        },
    )
    return True


async def _latest_progress_ts(session, run: Run) -> datetime | None:
    return await session.scalar(
        select(func.max(RunEvent.ts)).where(
            RunEvent.run_id == run.id,
            RunEvent.event_type.in_(RUN_PROGRESS_EVENT_TYPES),
        )
    )


async def _active_worker_count(session) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.kind == "worker", Agent.status == "ACTIVE")
        )
    ).scalar() or 0


async def _latest_event_ts(session, run: Run, event_type: str) -> datetime | None:
    return await session.scalar(
        select(func.max(RunEvent.ts)).where(RunEvent.run_id == run.id, RunEvent.event_type == event_type)
    )


async def _finalize_run_degraded(session, run: Run, *, reason: str, actor_type: str = "SYSTEM") -> bool:
    from app.services.state_guard import update_run_status

    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "COMPLETED", set_finished=True)
    if not ok:
        return False
    summary = dict(run.summary or {})
    summary["degraded_completion"] = True
    summary["degraded_reason"] = reason
    summary["degraded_at"] = datetime.now(timezone.utc).isoformat()
    summary["goal_state"] = "CONCLUDED_UNRESOLVABLE"
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_DEGRADED",
        actor_type=actor_type,
        tenant_id=run.tenant_id,
        payload={"reason": reason, "final_status": "COMPLETED"},
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_COMPLETED",
        actor_type=actor_type,
        tenant_id=run.tenant_id,
        payload={"final_status": "COMPLETED", "degraded": True, "reason": reason},
    )
    return True


def _is_budget_exhausted_failure(item: WorkItem) -> bool:
    result = item.result if isinstance(item.result, dict) else {}
    message = str(result.get("message") or "").lower()
    failure_class = str(result.get("failure_class") or "").lower()
    last_error = str(item.last_error or "").lower()
    return (
        "run_budget_exhausted" in message
        or "budget_exceeded" in message
        or "budget_exhausted" in message
        or failure_class in {"budget_exhausted", "budget_exceeded"}
        or "budget_exhausted" in last_error
        or "budget_exceeded" in last_error
    )


def _is_quota_exhausted_failure(item: WorkItem) -> bool:
    result = item.result if isinstance(item.result, dict) else {}
    error_kind = str(result.get("error_kind") or "").lower()
    error_message = str(result.get("error_message") or "").lower()
    last_error = str(item.last_error or "").lower()
    return (
        error_kind in {"model_error", "rate_limit_error"}
        and (
            "insufficient_quota" in error_message
            or "exceeded your current quota" in error_message
            or "insufficient_quota" in last_error
            or "exceeded your current quota" in last_error
        )
    )


def _is_operator_confirmation_failure(item: WorkItem) -> bool:
    result = item.result if isinstance(item.result, dict) else {}
    message = str(result.get("message") or "").lower()
    error = str(result.get("error") or "").lower()
    last_error = str(item.last_error or "").lower()
    markers = (
        "requires operator confirmation",
        "require operator confirmation",
        "operator confirmation before mutating",
        "approval required before mutating",
    )
    haystack = "\n".join((message, error, last_error))
    return any(marker in haystack for marker in markers)


async def _maybe_emit_budget_warning(session, run: Run) -> None:
    summary = dict(run.summary or {})
    contract = summary.get("execution_contract") if isinstance(summary.get("execution_contract"), dict) else {}
    budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    budget_mode = str(budget.get("budget_mode") or "").upper()
    if budget_mode != "CONSTRAINED":
        return
    now_ts = datetime.now(timezone.utc)
    latest_warning_ts = await _latest_event_ts(session, run, "RUN_BUDGET_WARNING")
    if latest_warning_ts is not None:
        if latest_warning_ts.tzinfo is None:
            latest_warning_ts = latest_warning_ts.replace(tzinfo=timezone.utc)
        if (now_ts - latest_warning_ts).total_seconds() < BUDGET_WARNING_EVENT_THROTTLE_SECONDS:
            return
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_BUDGET_WARNING",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "budget_mode": budget.get("budget_mode"),
            "remaining_tokens": budget.get("remaining_tokens"),
            "remaining_cost_cents": budget.get("remaining_cost_cents"),
            "escalation_reason": budget.get("escalation_reason"),
        },
    )


async def _pause_run_for_budget(session, run: Run, *, failed_items: list[WorkItem]) -> bool:
    from app.services.state_guard import update_run_status

    budget_failed = [item for item in failed_items if _is_budget_exhausted_failure(item)]
    if not budget_failed:
        return False
    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
    if not ok:
        return False
    summary = dict(run.summary or {})
    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
    summary["budget_pause"] = {
        "reason": "run_budget_exhausted",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "failed_work_item_ids": [str(item.id) for item in budget_failed],
    }
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_BUDGET_PAUSED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={"reason": "run_budget_exhausted", "failed_work_item_ids": [str(item.id) for item in budget_failed]},
    )
    return True


async def _pause_run_for_operator_confirmation(session, run: Run, *, failed_items: list[WorkItem]) -> bool:
    from app.services.state_guard import update_run_status

    blocked = [item for item in failed_items if _is_operator_confirmation_failure(item)]
    if not blocked:
        return False
    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
    if not ok:
        return False
    summary = dict(run.summary or {})
    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
    summary["operator_confirmation_pause"] = {
        "reason": "operator_confirmation_required",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "failed_work_item_ids": [str(item.id) for item in blocked],
    }
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_OPERATOR_ACTION_REQUIRED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "reason": "operator_confirmation_required",
            "failed_work_item_ids": [str(item.id) for item in blocked],
        },
    )
    return True


def _test_failure_signature(item: WorkItem) -> str:
    result = item.result if isinstance(item.result, dict) else {}
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    message = str(result.get("message") or "")
    last_error = str(item.last_error or "")
    # Keep only the leading failure slice to compare retry convergence.
    head = "\n".join(
        part.strip().lower()
        for part in (
            stdout[:600],
            stderr[:300],
            message[:120],
            last_error[:120],
        )
        if part
    )
    return head


async def _pause_run_for_recovery_stall(session, run: Run) -> bool:
    from app.services.state_guard import update_run_status

    recent_failed_tests = (
        await session.execute(
            select(WorkItem)
            .where(
                WorkItem.run_id == run.id,
                WorkItem.type == "RUN_TESTS",
                WorkItem.status == "FAILED",
            )
            .order_by(WorkItem.created_at.desc())
            .limit(MAX_IDENTICAL_TEST_FAILURES)
        )
    ).scalars().all()
    if len(recent_failed_tests) < MAX_IDENTICAL_TEST_FAILURES:
        return False

    signatures = [_test_failure_signature(item) for item in recent_failed_tests]
    if not signatures[0] or any(sig != signatures[0] for sig in signatures[1:]):
        return False

    oldest = recent_failed_tests[-1]
    failed_fix_count = (
        await session.execute(
            select(func.count())
            .select_from(WorkItem)
            .where(
                WorkItem.run_id == run.id,
                WorkItem.type == "FIX_TEST_FAILURE",
                WorkItem.status == "FAILED",
                WorkItem.created_at >= oldest.created_at,
            )
        )
    ).scalar() or 0
    if failed_fix_count == 0:
        return False

    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
    if not ok:
        return False

    summary = dict(run.summary or {})
    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
    summary["recovery_pause"] = {
        "reason": "recovery_no_progress",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "identical_test_failures": len(recent_failed_tests),
        "failed_fix_attempts": int(failed_fix_count),
    }
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_RECOVERY_PAUSED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        message="Paused run: repeated identical test failures after recovery attempts.",
        payload={
            "reason": "recovery_no_progress",
            "identical_test_failures": len(recent_failed_tests),
            "failed_fix_attempts": int(failed_fix_count),
        },
    )
    return True


async def _queue_goal_recovery_retry(session, run: Run, failed_items: list[WorkItem]) -> bool:
    settings = get_settings()
    summary = dict(run.summary or {})
    current_cycles = int(summary.get("goal_recovery_cycles") or 0)
    if current_cycles >= settings.runtime_goal_max_recovery_cycles:
        return False
    blocking_failed = [item for item in failed_items if is_blocking_failure(item)]
    if not blocking_failed:
        return False
    if any(_is_quota_exhausted_failure(item) for item in blocking_failed):
        return False
    if any(_is_operator_confirmation_failure(item) for item in blocking_failed):
        return False
    source = blocking_failed[0]
    next_cycle = current_cycles + 1
    recovery_payload = dict(source.payload or {})
    recovery_payload.update(
        {
            "recovery_action": "goal_recovery_retry",
            "recovery_source_id": str(source.id),
            "goal_recovery_cycle": next_cycle,
        }
    )
    recovery_item = WorkItem(
        project_id=source.project_id,
        tenant_id=source.tenant_id,
        run_id=source.run_id,
        type=source.type,
        key=f"{source.key or source.type}_RECOVERY_{next_cycle}",
        status="QUEUED",
        priority=max(source.priority + 1, 1),
        executor=source.executor,
        attempt=0,
        max_attempts=max(source.max_attempts, 1),
        required_capabilities=list(source.required_capabilities or []),
        payload=recovery_payload,
        depends_on_count=0,
    )
    session.add(recovery_item)
    await session.flush()

    source_result = dict(source.result or {})
    source_result["superseded"] = True
    source_result["superseded_by"] = str(recovery_item.id)
    source_result["superseded_reason"] = "goal_recovery_retry_spawned"
    source.result = source_result
    session.add(source)

    summary["goal_state"] = "RECOVERING"
    summary["goal_recovery_cycles"] = next_cycle
    summary["goal_last_recovery_source_work_item_id"] = str(source.id)
    run.summary = summary
    session.add(run)

    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        work_item_id=recovery_item.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={"work_item_id": str(recovery_item.id), "type": recovery_item.type, "reason": "goal_recovery_retry"},
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        work_item_id=source.id,
        event_type="WORK_ITEM_RECOVERY",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "work_item_id": str(source.id),
            "recovery_action": "goal_recovery_retry",
            "recovery_work_item_id": str(recovery_item.id),
            "recovery_cycle": next_cycle,
        },
        message="Goal recovery retry queued from terminal blocking failure.",
    )
    return True


async def tick(session):
    settings = get_settings()

    await reclaim_expired_work_items(session)
    await reclaim_orphaned_work_items(session)

    # finalize runs
    runs = (
        await session.execute(
            select(Run).where(Run.status.in_(["RUNNING", "QUEUED"]))
        )
    ).scalars().all()
    from app.services.state_guard import update_run_status
    for run in runs:
        run_summary = dict(run.summary or {})
        if "goal_state" not in run_summary:
            run_summary["goal_state"] = "ACTIVE"
            run.summary = run_summary
            session.add(run)

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
            if settings.runtime_never_fail_runs:
                ok = await _finalize_run_degraded(session, run, reason="review_diff_rejected")
            else:
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
            if ok:
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

        await _supersede_stale_failed_recoveries(session, run)

        failed_items = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.run_id == run.id,
                    WorkItem.status == "FAILED",
                )
            )
        ).scalars().all()
        failed_non_superseded = sum(
            1
            for item in failed_items
            if is_blocking_failure(item)
        )
        await _maybe_emit_budget_warning(session, run)
        recovery_pending = await has_pending_recovery_work(session, run.id)
        if recovery_pending:
            await sync_run_recovery_latch(session, run.id)
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
        runnable_items = await _runnable_queued_items(session, run) if queued else []
        if queued and active == 0 and runnable_items:
            await _nudge_worker_if_stalled(session, run, runnable_items, active)

        # Guard: active work items should still emit progress. If not, pause for operator recovery.
        if active > 0:
            last_progress = await _latest_progress_ts(session, run)
            progress_anchor = last_progress or run.updated_at or run.started_at or run.created_at
            if progress_anchor is not None and progress_anchor.tzinfo is None:
                progress_anchor = progress_anchor.replace(tzinfo=timezone.utc)
            stalled_for = (datetime.now(timezone.utc) - progress_anchor).total_seconds() if progress_anchor else 0.0
            if stalled_for >= ACTIVE_STALL_PAUSE_SECONDS:
                ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
                if ok:
                    summary = dict(run.summary or {})
                    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
                    summary["recovery_pause"] = {
                        "reason": "active_work_stalled_no_progress",
                        "paused_at": datetime.now(timezone.utc).isoformat(),
                        "active_count": int(active),
                        "queued_count": int(queued),
                        "stalled_for_seconds": int(stalled_for),
                    }
                    run.summary = summary
                    session.add(run)
                    await record_event(
                        session,
                        project_id=run.project_id,
                        run_id=run.id,
                        event_type="RUN_ACTIVE_STALLED_PAUSED",
                        actor_type="SYSTEM",
                        tenant_id=run.tenant_id,
                        message="Paused run: active work item execution stalled with no progress signal.",
                        payload={
                            "reason": "active_work_stalled_no_progress",
                            "active_count": int(active),
                            "queued_count": int(queued),
                            "stalled_for_seconds": int(stalled_for),
                        },
                    )
                    continue

        # Watchdog: avoid infinite RUNNING/QUEUED when there is no execution progress.
        if queued and active == 0:
            last_progress = await _latest_progress_ts(session, run)
            progress_anchor = last_progress or run.updated_at or run.started_at or run.created_at
            if progress_anchor is not None and progress_anchor.tzinfo is None:
                progress_anchor = progress_anchor.replace(tzinfo=timezone.utc)
            stalled_for = (datetime.now(timezone.utc) - progress_anchor).total_seconds() if progress_anchor else 0.0
            summary = dict(run.summary or {})
            if stalled_for < STALL_TIMEOUT_SECONDS and summary.get("stall_recovery_attempts"):
                summary["stall_recovery_attempts"] = 0
                run.summary = summary
                session.add(run)
            if stalled_for >= STALL_TIMEOUT_SECONDS:
                active_workers = await _active_worker_count(session)
                now_ts = datetime.now(timezone.utc)
                latest_stalled_ts = await _latest_event_ts(session, run, "RUN_STALLED")
                if latest_stalled_ts is not None:
                    if latest_stalled_ts.tzinfo is None:
                        latest_stalled_ts = latest_stalled_ts.replace(tzinfo=timezone.utc)
                    else:
                        latest_stalled_ts = latest_stalled_ts.astimezone(timezone.utc)
                if (
                    latest_stalled_ts is None
                    or (now_ts - latest_stalled_ts).total_seconds() >= STALL_EVENT_THROTTLE_SECONDS
                ):
                    await record_event(
                        session,
                        project_id=run.project_id,
                        run_id=run.id,
                        event_type="RUN_STALLED",
                        actor_type="SYSTEM",
                        tenant_id=run.tenant_id,
                        payload={
                            "stalled_for_seconds": int(stalled_for),
                            "queued_count": int(queued),
                            "runnable_queued_count": int(len(runnable_items)),
                            "active_worker_count": int(active_workers),
                        },
                    )
                if active_workers == 0:
                    if recovery_pending:
                        continue
                    await _cancel_terminally_blocked_items(session, run)
                    if settings.runtime_never_fail_runs:
                        await _finalize_run_degraded(session, run, reason="stalled_no_active_workers")
                    else:
                        ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "FAILED", set_finished=True)
                        if ok:
                            await record_event(
                                session,
                                project_id=run.project_id,
                                run_id=run.id,
                                event_type="RUN_FAILED",
                                actor_type="SYSTEM",
                                tenant_id=run.tenant_id,
                                payload={"reason": "stalled_no_active_workers"},
                            )
                    continue
                attempts = int(summary.get("stall_recovery_attempts") or 0) + 1
                summary["stall_recovery_attempts"] = attempts
                run.summary = summary
                session.add(run)

                await reclaim_expired_work_items(session, run_id=run.id)
                await reclaim_orphaned_work_items(session, run_id=run.id)
                runnable_after_reclaim = await _runnable_queued_items(session, run)
                nudged = await _nudge_worker_if_stalled(session, run, runnable_after_reclaim, active)
                await record_event(
                    session,
                    project_id=run.project_id,
                    run_id=run.id,
                    event_type="RUN_STALL_RECOVERY_ATTEMPT",
                    actor_type="SYSTEM",
                    tenant_id=run.tenant_id,
                    payload={
                        "attempt": attempts,
                        "max_attempts": STALL_RECOVERY_MAX_ATTEMPTS,
                        "stalled_for_seconds": int(stalled_for),
                        "runnable_after_reclaim": int(len(runnable_after_reclaim)),
                        "worker_nudged": bool(nudged),
                    },
                )
                if attempts <= STALL_RECOVERY_MAX_ATTEMPTS:
                    continue

                await _cancel_terminally_blocked_items(session, run)
                if settings.runtime_never_fail_runs:
                    await _finalize_run_degraded(session, run, reason="stalled_no_progress")
                else:
                    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "FAILED", set_finished=True)
                    if ok:
                        await record_event(
                            session,
                            project_id=run.project_id,
                            run_id=run.id,
                            event_type="RUN_FAILED",
                            actor_type="SYSTEM",
                            tenant_id=run.tenant_id,
                            payload={"reason": "stalled_no_progress"},
                        )
                continue

        if failed_non_superseded and active == 0 and queued and not recovery_pending:
            runnable_queued = len(runnable_items)
            if runnable_queued == 0:
                canceled_count = await _cancel_terminally_blocked_items(session, run)
                if canceled_count:
                    queued = 0

        if failed_non_superseded and active == 0 and queued == 0 and not recovery_pending:
            if await _pause_run_for_budget(session, run, failed_items=failed_items):
                continue
            if await _pause_run_for_operator_confirmation(session, run, failed_items=failed_items):
                continue
            if await _pause_run_for_recovery_stall(session, run):
                continue
            if settings.runtime_goal_orchestration_enabled:
                spawned = await _queue_goal_recovery_retry(session, run, failed_items)
                if spawned:
                    continue
            if settings.runtime_never_fail_runs:
                ok = await _finalize_run_degraded(session, run, reason="goal_concluded_unresolvable")
                if not ok:
                    continue
            else:
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
                        actor_type="SYSTEM",
                        tenant_id=locked.tenant_id,
                        message=str(exc),
                        payload={
                            "branch_name": locked.branch_name,
                            "workspace_status": locked.workspace_status,
                            "manual_push_required": True,
                        },
                    )

            locked.status = final_status
            locked.finished_at = datetime.now(timezone.utc)
            summary = dict(locked.summary or {})
            summary["goal_state"] = "DONE"
            if final_status == "COMPLETED":
                summary.pop("degraded_completion", None)
                summary.pop("degraded_reason", None)
                summary.pop("degraded_at", None)
            locked.summary = summary
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
