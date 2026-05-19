from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select, func

from app.core.config import get_settings
from app.db.models import Agent, Run, RunEvent, Task, WorkItem, WorkItemEdge
from app.db.session import SessionLocal
from app.runtime.leases import reclaim_expired_work_items, reclaim_orphaned_work_items
from app.runtime.recovery_policy import has_pending_recovery_work, sync_run_recovery_latch
from app.services.event_log import record_event
from app.services.runtime_lineage import link_run_to_work_item
from app.services.run_delivery import publish_run_branch_if_ready
from app.services.work_item_state import is_blocking_failure, is_dependency_satisfied, is_superseded_failure
from app.api.v1.lifecycle_score import lifecycle_score
settings = get_settings()

VALIDATION_TERMINAL_TYPES = {"WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"}
RUN_PROGRESS_EVENT_TYPES = {"WORK_ITEM_CLAIMED", "WORK_ITEM_DONE", "WORK_ITEM_FAILED", "WORK_ITEM_SKIPPED"}
STALL_TIMEOUT_SECONDS = 90
STALL_EVENT_THROTTLE_SECONDS = 60
STALL_RECOVERY_MAX_ATTEMPTS = 2
STALL_PAUSE_AUTO_RESUME_MAX_ATTEMPTS = 8
STALL_PAUSE_AUTO_RESUME_COOLDOWN_SECONDS = 10
ACTIVE_STALL_PAUSE_SECONDS = 600
BUDGET_WARNING_EVENT_THROTTLE_SECONDS = 120
SPEND_WARNING_EVENT_THROTTLE_SECONDS = 120
MAX_IDENTICAL_TEST_FAILURES = 3
AUTO_PHASE_MAX_FILES = 6
AUTO_PHASE_DECOMPOSE_MIN_FILES = 7
AUTO_PHASE_DECOMPOSE_MAX_FILES = 20


def _governance_mode(run: Run) -> str:
    summary = run.summary if isinstance(run.summary, dict) else {}
    mode = str(summary.get("repository_state") or "").strip().upper()
    if mode:
        return mode
    task_source = str(summary.get("task_source") or "").strip().lower()
    task_source_type = str(summary.get("task_source_type") or "").strip().lower()
    requirement_id = str(summary.get("requirement_id") or "").strip().lower()
    if task_source == "genesis" or task_source_type == "genesis_setup" or requirement_id.startswith("genesis."):
        return "GENESIS"
    return "ACTIVE_PRODUCT"


def _is_bootstrap_mode(run: Run) -> bool:
    return _governance_mode(run) in {"GENESIS", "EARLY_BUILD"}


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


async def _normalize_topology_planning_capability_requirements(session, run: Run) -> None:
    queued_topology_items = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == run.id,
                WorkItem.type == "PLAN_BACKEND_TOPOLOGY",
                WorkItem.status == "QUEUED",
            )
        )
    ).scalars().all()
    if not queued_topology_items:
        return
    for item in queued_topology_items:
        caps = list(item.required_capabilities or [])
        if "capability_governance" not in caps:
            continue
        normalized = [cap for cap in caps if cap != "capability_governance"]
        if "plan" not in normalized:
            normalized.append("plan")
        item.required_capabilities = normalized
        session.add(item)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=item.id,
            event_type="WORK_ITEM_REQUIREMENTS_NORMALIZED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            message="Normalized topology planning capability requirements for worker compatibility.",
            payload={
                "work_item_id": str(item.id),
                "before": caps,
                "after": normalized,
                "reason": "legacy_capability_governance_requirement",
            },
        )


async def _maybe_auto_resume_stall_paused_run(session, run: Run) -> bool:
    from app.services.state_guard import update_run_status

    settings = get_settings()
    if not settings.runtime_never_fail_runs:
        return False
    if str(run.status or "").upper() != "PAUSED":
        return False

    summary = dict(run.summary or {})
    recovery_pause = summary.get("recovery_pause") if isinstance(summary.get("recovery_pause"), dict) else {}
    reason = str(recovery_pause.get("reason") or "").strip().lower()
    if reason not in {"stalled_no_progress", "stalled_no_active_workers", "active_work_stalled_no_progress"}:
        return False

    now_ts = datetime.now(timezone.utc)
    attempts = int(summary.get("stall_pause_auto_resume_attempts") or 0)
    if attempts >= STALL_PAUSE_AUTO_RESUME_MAX_ATTEMPTS:
        return False

    updated_at = run.updated_at
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if updated_at is not None:
        elapsed = (now_ts - updated_at).total_seconds()
        if elapsed < STALL_PAUSE_AUTO_RESUME_COOLDOWN_SECONDS:
            return False

    ok = await update_run_status(session, run.id, ["PAUSED"], "QUEUED", set_finished=False)
    if not ok:
        return False

    summary["stall_pause_auto_resume_attempts"] = attempts + 1
    summary["stall_pause_last_auto_resumed_at"] = now_ts.isoformat()
    summary["goal_state"] = "ACTIVE"
    run.summary = summary
    run.finished_at = None
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_AUTO_RESUMED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        message="Auto-resumed paused run to continue downstream execution.",
        payload={
            "reason": reason,
            "attempt": attempts + 1,
            "max_attempts": STALL_PAUSE_AUTO_RESUME_MAX_ATTEMPTS,
            "cooldown_seconds": STALL_PAUSE_AUTO_RESUME_COOLDOWN_SECONDS,
        },
    )
    return True


def _work_item_required_and_criticality(work_item: WorkItem) -> tuple[bool, str]:
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    required_raw = payload.get("required", None)
    if isinstance(required_raw, bool):
        required = required_raw
    else:
        required = work_item.type in {
            "PLAN_DAG",
            "PLAN_BACKEND_TOPOLOGY",
            "CODE_BACKEND",
            "CODE_FRONTEND",
            "GENERATE_ROUTE",
            "GENERATE_SERVICE",
            "GENERATE_REPOSITORY",
            "GENERATE_CAPABILITY_BINDING",
        }
    criticality = str(payload.get("criticality") or "").strip().upper()
    if not criticality:
        criticality = "OPTIONAL" if not required else "FEATURE"
    return required, criticality


async def _classify_terminal_quality(session, run: Run) -> tuple[str, dict[str, int]]:
    items = (
        await session.execute(select(WorkItem).where(WorkItem.run_id == run.id))
    ).scalars().all()
    counts: dict[str, int] = {}
    critical_failed = 0
    optional_failed = 0
    for item in items:
        status = str(item.status or "").upper()
        counts[status] = counts.get(status, 0) + 1
        if status not in {"FAILED", "CANCELED", "BLOCKED"}:
            continue
        required, criticality = _work_item_required_and_criticality(item)
        if required or criticality in {"FOUNDATION", "CRITICAL"}:
            critical_failed += 1
        else:
            optional_failed += 1
    counts["critical_failed"] = int(critical_failed)
    counts["optional_failed"] = int(optional_failed)
    if critical_failed > 0:
        return "DEGRADED_COMPLETION", counts
    if optional_failed > 0:
        return "COMPLETED_WITH_RECOVERY", counts
    recovery_attempts = (
        await session.execute(
            select(func.count())
            .select_from(RunEvent)
            .where(
                RunEvent.run_id == run.id,
                RunEvent.event_type.in_(["WORK_ITEM_RECOVERY", "RECOVERY_ATTEMPT_SUCCEEDED"]),
            )
        )
    ).scalar() or 0
    if int(recovery_attempts) > 0:
        return "COMPLETED_WITH_RECOVERY", counts
    return "COMPLETED_CLEAN", counts


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
    summary["terminal_quality"] = "DEGRADED_COMPLETION"
    run.summary = summary
    session.add(run)
    await _sync_task_status_for_terminal_run(session, run, run_status="COMPLETED", reason=reason)
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
        event_type="RUN_TERMINAL_CLASSIFIED",
        actor_type=actor_type,
        tenant_id=run.tenant_id,
        payload={"terminal_quality": "DEGRADED_COMPLETION", "reason": reason},
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


async def _mark_run_failed(
    session,
    run: Run,
    *,
    reason: str,
    actor_type: str = "SYSTEM",
) -> bool:
    """Transition a run to FAILED with a defensive fallback when guarded update misses."""
    from app.services.state_guard import update_run_status

    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "FAILED", set_finished=True)
    if not ok:
        # Defensive fallback: some DB backends can report rowcount=0 for guarded updates
        # even when the in-memory run still reflects a mutable RUNNING/QUEUED state.
        if run.status not in {"RUNNING", "QUEUED"}:
            return False
        run.status = "FAILED"
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_FAILED",
        actor_type=actor_type,
        tenant_id=run.tenant_id,
        payload={"reason": reason},
    )
    await _sync_task_status_for_terminal_run(session, run, run_status="FAILED", reason=reason)
    return True


async def _sync_task_status_for_terminal_run(
    session,
    run: Run,
    *,
    run_status: str,
    reason: str | None = None,
) -> None:
    task = await session.scalar(
        select(Task)
        .where(
            Task.run_id == run.id,
            Task.project_id == run.project_id,
            Task.tenant_id == run.tenant_id,
            Task.deleted_at.is_(None),
        )
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .limit(1)
    )
    if task is None:
        summary = run.summary if isinstance(run.summary, dict) else {}
        raw_task_id = summary.get("task_id")
        try:
            parsed_task_id = uuid.UUID(str(raw_task_id)) if raw_task_id else None
        except (TypeError, ValueError, AttributeError):
            parsed_task_id = None
        if parsed_task_id is not None:
            task = await session.scalar(
                select(Task).where(
                    Task.id == parsed_task_id,
                    Task.project_id == run.project_id,
                    Task.tenant_id == run.tenant_id,
                    Task.deleted_at.is_(None),
                )
            )
    if task is None:
        return

    normalized = str(run_status or "").upper()
    if normalized == "COMPLETED":
        task.status = "DONE"
        task.last_error = None
    elif normalized == "FAILED":
        task.status = "FAILED"
        if reason:
            task.last_error = reason
    elif normalized == "CANCELED":
        task.status = "CANCELED"
    if task.started_at is None:
        task.started_at = run.started_at
    if task.status in {"DONE", "FAILED", "CANCELED"}:
        task.finished_at = run.finished_at or datetime.now(timezone.utc)
    result_payload = dict(task.result_payload or {})
    result_payload["run_id"] = str(run.id)
    result_payload["run_status"] = normalized
    if reason:
        result_payload["run_reason"] = reason
    task.result_payload = result_payload
    task.run_id = run.id
    session.add(task)


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


def _is_patch_too_large_failure(item: WorkItem) -> bool:
    result = item.result if isinstance(item.result, dict) else {}
    message = str(result.get("message") or "").lower()
    error = str(result.get("error") or "").lower()
    failure_class = str(result.get("failure_class") or "").lower()
    last_error = str(item.last_error or "").lower()
    haystack = "\n".join((message, error, last_error))
    return (
        "patch too large for" in haystack
        or "patch_too_large" in haystack
        or failure_class in {"patch_too_large", "patch_apply_failure"}
    )


def _verification_from_failed_item(item: WorkItem) -> dict:
    result = item.result if isinstance(item.result, dict) else {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
    return verification


def _verification_file_scope(item: WorkItem) -> list[str]:
    verification = _verification_from_failed_item(item)
    for key in ("verified_files", "actual_files"):
        value = verification.get(key)
        if isinstance(value, list):
            files = [str(path).strip() for path in value if isinstance(path, str) and path.strip()]
            if files:
                return list(dict.fromkeys(files))
    payload = item.payload if isinstance(item.payload, dict) else {}
    for key in ("target_files", "files", "expected_files"):
        value = payload.get(key)
        if isinstance(value, list):
            files = [str(path).strip() for path in value if isinstance(path, str) and path.strip()]
            if files:
                return list(dict.fromkeys(files))
    return []


def _is_decomposable_operator_confirmation(item: WorkItem) -> bool:
    if not _is_operator_confirmation_failure(item):
        return False
    verification = _verification_from_failed_item(item)
    file_count = int(verification.get("file_count") or 0)
    return AUTO_PHASE_DECOMPOSE_MIN_FILES <= file_count <= AUTO_PHASE_DECOMPOSE_MAX_FILES


def _chunked(values: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [values]
    return [values[i : i + size] for i in range(0, len(values), size)]


async def _auto_decompose_operator_confirmation(session, run: Run, *, failed_items: list[WorkItem]) -> bool:
    candidates = [
        item
        for item in failed_items
        if is_blocking_failure(item) and not is_superseded_failure(item) and _is_decomposable_operator_confirmation(item)
    ]
    if not candidates:
        return False

    summary = dict(run.summary or {})
    if summary.get("auto_phase_decomposition_in_progress"):
        return False

    source = sorted(candidates, key=lambda item: (item.priority, item.created_at), reverse=True)[0]
    scoped_files = _verification_file_scope(source)
    if not scoped_files:
        return False
    file_chunks = _chunked(scoped_files, AUTO_PHASE_MAX_FILES)
    if len(file_chunks) <= 1:
        return False

    task_payload = dict(source.payload or {})
    base_key = source.key or source.type
    created: list[WorkItem] = []
    predecessor_id = None

    for index, chunk in enumerate(file_chunks, start=1):
        phase_payload = dict(task_payload)
        phase_payload["files"] = list(chunk)
        phase_payload["target_files"] = list(chunk)
        phase_payload["expected_files"] = list(chunk)
        phase_payload["recovery_action"] = "auto_phase_decomposition"
        phase_payload["recovery_source_id"] = str(source.id)
        phase_payload["phase_index"] = index
        phase_payload["phase_total"] = len(file_chunks)
        wi = WorkItem(
            project_id=source.project_id,
            tenant_id=source.tenant_id,
            run_id=source.run_id,
            type=source.type,
            key=f"{base_key}_PHASE_{index}",
            status="QUEUED",
            priority=max(source.priority + 1, 1),
            executor=source.executor,
            attempt=0,
            max_attempts=max(source.max_attempts, 1),
            required_capabilities=list(source.required_capabilities or []),
            payload=phase_payload,
            depends_on_count=1 if predecessor_id else 0,
        )
        session.add(wi)
        await session.flush()
        await link_run_to_work_item(session, wi)
        created.append(wi)
        if predecessor_id:
            session.add(
                WorkItemEdge(
                    tenant_id=source.tenant_id,
                    run_id=source.run_id,
                    from_work_item_id=predecessor_id,
                    to_work_item_id=wi.id,
                )
            )
        predecessor_id = wi.id

    followup_types = ["WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"]
    last_phase_id = predecessor_id
    for item_type in followup_types:
        candidate = await session.scalar(
            select(WorkItem)
            .where(WorkItem.run_id == run.id, WorkItem.type == item_type)
            .order_by(WorkItem.created_at.desc())
            .limit(1)
        )
        if candidate is None:
            continue
        replay_payload = dict(candidate.payload or {})
        replay_payload["recovery_action"] = "auto_phase_decomposition"
        replay_payload["recovery_source_id"] = str(source.id)
        replay = WorkItem(
            project_id=source.project_id,
            tenant_id=source.tenant_id,
            run_id=source.run_id,
            type=candidate.type,
            key=f"{candidate.key or candidate.type}_PHASED_{uuid.uuid4().hex[:4]}",
            status="QUEUED",
            priority=max(candidate.priority, 1),
            executor=candidate.executor,
            attempt=0,
            max_attempts=max(candidate.max_attempts, 1),
            required_capabilities=list(candidate.required_capabilities or []),
            payload=replay_payload,
            depends_on_count=1 if last_phase_id else 0,
        )
        session.add(replay)
        await session.flush()
        await link_run_to_work_item(session, replay)
        if last_phase_id:
            session.add(
                WorkItemEdge(
                    tenant_id=source.tenant_id,
                    run_id=source.run_id,
                    from_work_item_id=last_phase_id,
                    to_work_item_id=replay.id,
                )
            )
        last_phase_id = replay.id
        created.append(replay)

    for blocked in candidates:
        blocked_result = dict(blocked.result or {})
        blocked_result["superseded"] = True
        blocked_result["superseded_reason"] = "auto_phase_decomposition"
        blocked_result["superseded_by"] = str(created[0].id)
        blocked.result = blocked_result
        session.add(blocked)

    summary["goal_state"] = "RECOVERING"
    summary["auto_phase_decomposition_in_progress"] = True
    summary["auto_phase_decomposition"] = {
        "source_work_item_id": str(source.id),
        "created_work_item_ids": [str(item.id) for item in created],
        "phase_count": len(file_chunks),
        "file_count": len(scoped_files),
        "max_files_per_phase": AUTO_PHASE_MAX_FILES,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    run.summary = summary
    session.add(run)

    for item in created:
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=item.id,
            event_type="WORK_ITEM_CREATED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            payload={"work_item_id": str(item.id), "type": item.type, "reason": "auto_phase_decomposition"},
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
            "recovery_action": "auto_phase_decomposition",
            "recovery_work_item_ids": [str(item.id) for item in created],
            "phase_count": len(file_chunks),
        },
        message="Auto phase decomposition queued from operator confirmation scope.",
    )
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_AUTO_DECOMPOSED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "source_work_item_id": str(source.id),
            "phase_count": len(file_chunks),
            "file_count": len(scoped_files),
            "max_files_per_phase": AUTO_PHASE_MAX_FILES,
        },
    )
    return True


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


async def _maybe_emit_run_spend_warning(session, run: Run) -> None:
    summary = dict(run.summary or {})
    contract = summary.get("execution_contract") if isinstance(summary.get("execution_contract"), dict) else {}
    budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    used_cost_cents = float(budget.get("used_cost_cents") or 0.0)
    soft_limit = max(0.0, float(get_settings().runtime_run_spend_soft_limit_cents))
    if soft_limit <= 0.0 or used_cost_cents < soft_limit:
        return
    now_ts = datetime.now(timezone.utc)
    latest_warning_ts = await _latest_event_ts(session, run, "RUN_SPEND_WARNING")
    if latest_warning_ts is not None:
        if latest_warning_ts.tzinfo is None:
            latest_warning_ts = latest_warning_ts.replace(tzinfo=timezone.utc)
        if (now_ts - latest_warning_ts).total_seconds() < SPEND_WARNING_EVENT_THROTTLE_SECONDS:
            return
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_SPEND_WARNING",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "used_cost_cents": round(used_cost_cents, 4),
            "soft_limit_cents": soft_limit,
        },
    )


async def _pause_run_for_spend_guard(session, run: Run) -> bool:
    from app.services.state_guard import update_run_status

    summary = dict(run.summary or {})
    contract = summary.get("execution_contract") if isinstance(summary.get("execution_contract"), dict) else {}
    budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    used_cost_cents = float(budget.get("used_cost_cents") or 0.0)
    hard_limit = max(0.0, float(get_settings().runtime_run_spend_hard_limit_cents))
    if hard_limit <= 0.0 or used_cost_cents < hard_limit:
        return False
    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
    if not ok:
        return False
    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
    summary["spend_pause"] = {
        "reason": "run_spend_hard_limit_reached",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "used_cost_cents": round(used_cost_cents, 4),
        "hard_limit_cents": hard_limit,
    }
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_SPEND_PAUSED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "reason": "run_spend_hard_limit_reached",
            "used_cost_cents": round(used_cost_cents, 4),
            "hard_limit_cents": hard_limit,
        },
        message="Paused run: hard run-spend limit reached.",
    )
    return True


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

    settings = get_settings()
    if bool(getattr(settings, "codex_bypass_operator_confirmation_required", False)):
        return False

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


async def _pause_run_for_patch_scope(session, run: Run, *, failed_items: list[WorkItem]) -> bool:
    from app.services.state_guard import update_run_status

    if _is_bootstrap_mode(run):
        return False
    blocked = [item for item in failed_items if _is_patch_too_large_failure(item)]
    if not blocked:
        return False

    requires_decomposition = False
    for item in blocked:
        payload = item.payload if isinstance(item.payload, dict) else {}
        recovery_strategy = str(payload.get("recovery_strategy") or "").strip().lower()
        recovery_action = str(payload.get("recovery_action") or "").strip().lower()
        if recovery_strategy == "write_file_preferred" or recovery_action == "goal_recovery_retry":
            requires_decomposition = True
            break
    if not requires_decomposition:
        return False

    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
    if not ok:
        return False
    summary = dict(run.summary or {})
    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
    summary["patch_scope_pause"] = {
        "reason": "patch_scope_too_large_requires_decomposition",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "failed_work_item_ids": [str(item.id) for item in blocked],
    }
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_DECOMPOSITION_REQUIRED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "reason": "patch_scope_too_large_requires_decomposition",
            "failed_work_item_ids": [str(item.id) for item in blocked],
        },
        message="Paused run: patch scope exceeded bounded mutation policy; decomposition required.",
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


def _is_fix_patch_apply_failure(item: WorkItem) -> bool:
    if item.type != "FIX_TEST_FAILURE" or str(item.status or "").upper() != "FAILED":
        return False
    result = item.result if isinstance(item.result, dict) else {}
    message = str(result.get("message") or "")
    error = str(result.get("error") or "")
    last_error = str(item.last_error or "")
    haystack = f"{message}\n{error}\n{last_error}".lower()
    markers = (
        "patch apply error",
        "patch check failed",
        "patch does not apply",
        "corrupt patch",
    )
    return any(marker in haystack for marker in markers)


async def _pause_run_for_fix_patch_apply_loop(session, run: Run) -> bool:
    from app.services.state_guard import update_run_status

    recent_failed_fixes = (
        await session.execute(
            select(WorkItem)
            .where(
                WorkItem.run_id == run.id,
                WorkItem.type == "FIX_TEST_FAILURE",
                WorkItem.status == "FAILED",
            )
            .order_by(WorkItem.created_at.desc())
            .limit(2)
        )
    ).scalars().all()
    if len(recent_failed_fixes) < 2 or not all(_is_fix_patch_apply_failure(item) for item in recent_failed_fixes):
        return False

    latest_failed_run_tests = await session.scalar(
        select(WorkItem)
        .where(
            WorkItem.run_id == run.id,
            WorkItem.type == "RUN_TESTS",
            WorkItem.status == "FAILED",
        )
        .order_by(WorkItem.created_at.desc())
        .limit(1)
    )
    if latest_failed_run_tests is None:
        return False

    newest_fix = recent_failed_fixes[0]
    if newest_fix.created_at is None or latest_failed_run_tests.created_at is None:
        return False
    if newest_fix.created_at < latest_failed_run_tests.created_at:
        return False

    ok = await update_run_status(session, run.id, ["RUNNING", "QUEUED"], "PAUSED", set_finished=False)
    if not ok:
        return False
    summary = dict(run.summary or {})
    summary["goal_state"] = "NEEDS_HUMAN_INPUT"
    summary["recovery_pause"] = {
        "reason": "fix_patch_apply_loop",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "failed_fix_work_item_ids": [str(item.id) for item in recent_failed_fixes],
        "source_run_tests_work_item_id": str(latest_failed_run_tests.id),
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
        message="Paused run: repeated FIX_TEST_FAILURE patch-apply errors for the same failing tests.",
        payload={
            "reason": "fix_patch_apply_loop",
            "failed_fix_work_item_ids": [str(item.id) for item in recent_failed_fixes],
            "source_run_tests_work_item_id": str(latest_failed_run_tests.id),
        },
    )
    return True


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
    bootstrap_mode = _is_bootstrap_mode(run)
    if (not bootstrap_mode) and any(_is_operator_confirmation_failure(item) for item in blocking_failed):
        return False
    source = blocking_failed[0]
    source_result = source.result if isinstance(source.result, dict) else {}
    source_stop_reason = str(source_result.get("stop_reason") or source_result.get("message") or "").strip().lower()
    source_approval_required = source_result.get("approval_required")
    # Fail fast for internal policy stops that are not waiting on explicit operator approval.
    # In bypass mode we allow a recovery retry so patched guardrails can continue execution.
    bypass_operator_confirmation = bool(
        getattr(settings, "codex_bypass_operator_confirmation_required", False)
    )
    if (
        source_stop_reason == "human_review_required"
        and source_approval_required is False
        and not bypass_operator_confirmation
    ):
        return False
    source_last_error = str(source.last_error or "").lower()
    source_failure_class = str(source_result.get("failure_class") or "").strip().lower()
    source_failure_type = str(source_result.get("failure_type") or "").strip().lower()
    output_contract_invalid = (
        source_failure_class == "output_contract_invalid"
        or source_failure_type == "parser_error"
        or "output_contract_invalid" in source_last_error
    )
    source_payload = source.payload if isinstance(source.payload, dict) else {}
    source_recovery_strategy = str(source_payload.get("recovery_strategy") or "").strip().lower()
    source_strict_contract_mode = bool(source_payload.get("strict_output_contract_mode"))
    if output_contract_invalid and source_recovery_strategy == "write_file_preferred" and source_strict_contract_mode:
        return False
    next_cycle = current_cycles + 1
    recovery_payload = dict(source_payload)
    recovery_payload.update(
        {
            "recovery_action": "goal_recovery_retry",
            "recovery_source_id": str(source.id),
            "goal_recovery_cycle": next_cycle,
        }
    )
    if output_contract_invalid and source.type == "CODE_FRONTEND":
        recovery_payload["recovery_strategy"] = "write_file_preferred"
        recovery_payload["recovery_reason"] = "output_contract_invalid"
        recovery_payload["strict_output_contract_mode"] = True
        recovery_payload["prior_output_contract_failures"] = int(
            recovery_payload.get("prior_output_contract_failures") or 0
        ) + 1
        recovery_payload["recovery_action"] = "retry_with_write_file"
    if bootstrap_mode and source.type in {"CODE_BACKEND", "CODE_FRONTEND"}:
        recovery_payload.setdefault("recovery_strategy", "write_file_preferred")
        recovery_payload.setdefault("recovery_reason", "bootstrap_mode_retry")
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

    source_result = dict(source_result or {})
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


async def _requeue_validation_after_recovery(session, run: Run) -> bool:
    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id)
            .order_by(WorkItem.created_at.asc())
        )
    ).scalars().all()
    if not work_items:
        return False

    by_type: dict[str, list[WorkItem]] = {}
    for item in work_items:
        by_type.setdefault(item.type, []).append(item)

    validation_types = ["WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"]
    # Only replay validation if no active/queued validation work exists and there is canceled validation to replay.
    has_live_validation = any(
        any(item.status in {"QUEUED", "RUNNING", "CLAIMED"} for item in by_type.get(item_type, []))
        for item_type in validation_types
    )
    if has_live_validation:
        return False
    if not any(any(item.status == "CANCELED" for item in by_type.get(item_type, [])) for item_type in validation_types):
        return False

    latest_recovery_code = next(
        (
            item
            for item in reversed(work_items)
            if item.type in {"CODE_BACKEND", "CODE_FRONTEND"}
            and item.status == "DONE"
            and isinstance(item.payload, dict)
            and str(item.payload.get("recovery_action") or "") in {"goal_recovery_retry", "auto_phase_decomposition"}
        ),
        None,
    )
    if latest_recovery_code is None:
        return False

    summary = dict(run.summary or {})
    replayed_sources = summary.get("validation_replay_sources")
    if not isinstance(replayed_sources, list):
        replayed_sources = []
    replayed_source_ids = {
        str(source_id).strip()
        for source_id in replayed_sources
        if str(source_id).strip()
    }
    latest_recovery_id = str(latest_recovery_code.id)
    if latest_recovery_id in replayed_source_ids:
        return False
    replay_limit = max(0, int(get_settings().runtime_validation_replay_max_per_run))
    if replay_limit > 0 and len(replayed_source_ids) >= replay_limit:
        return False

    predecessor_id: uuid.UUID | None = latest_recovery_code.id
    created: list[WorkItem] = []
    for item_type in validation_types:
        template = next((item for item in reversed(by_type.get(item_type, [])) if item.status == "CANCELED"), None)
        if template is None:
            continue
        payload = dict(template.payload or {})
        payload["recovery_action"] = "replay_validation_after_recovery"
        payload["recovery_source_id"] = str(latest_recovery_code.id)
        replay = WorkItem(
            project_id=run.project_id,
            tenant_id=run.tenant_id,
            run_id=run.id,
            type=template.type,
            key=f"{template.key or template.type}_REPLAY_{uuid.uuid4().hex[:4]}",
            status="QUEUED",
            priority=max(template.priority, 1),
            executor=template.executor,
            attempt=0,
            max_attempts=max(template.max_attempts, 1),
            required_capabilities=list(template.required_capabilities or []),
            payload=payload,
            depends_on_count=1 if predecessor_id else 0,
        )
        session.add(replay)
        await session.flush()
        await link_run_to_work_item(session, replay)
        if predecessor_id:
            session.add(
                WorkItemEdge(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    from_work_item_id=predecessor_id,
                    to_work_item_id=replay.id,
                )
            )
        predecessor_id = replay.id
        created.append(replay)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=replay.id,
            event_type="WORK_ITEM_CREATED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            payload={"work_item_id": str(replay.id), "type": replay.type, "reason": "replay_validation_after_recovery"},
        )

    if not created:
        return False

    summary["validation_replay"] = {
        "reason": "recovery_completed_before_validation",
        "source_work_item_id": latest_recovery_id,
        "created_work_item_ids": [str(item.id) for item in created],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    replayed_source_ids.add(latest_recovery_id)
    summary["validation_replay_sources"] = sorted(replayed_source_ids)
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_VALIDATION_REPLAY_QUEUED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "reason": "recovery_completed_before_validation",
            "source_work_item_id": str(latest_recovery_code.id),
            "created_work_item_ids": [str(item.id) for item in created],
        },
    )
    return True


async def _requeue_execution_after_plan_recovery(session, run: Run) -> bool:
    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id)
            .order_by(WorkItem.created_at.asc())
        )
    ).scalars().all()
    if not work_items:
        return False

    by_type: dict[str, list[WorkItem]] = {}
    for item in work_items:
        by_type.setdefault(item.type, []).append(item)

    replay_types = [
        "PLAN_BACKEND_TOPOLOGY",
        "GENERATE_ROUTE",
        "GENERATE_SERVICE",
        "GENERATE_REPOSITORY",
        "GENERATE_CAPABILITY_BINDING",
        "WRITE_TESTS",
        "REVIEW_DIFF",
        "RUN_TESTS",
        "REVIEW_INTEGRATION",
    ]

    has_live_replay_types = any(
        any(item.status in {"QUEUED", "RUNNING", "CLAIMED"} for item in by_type.get(item_type, []))
        for item_type in replay_types
    )
    if has_live_replay_types:
        return False
    if not any(any(item.status == "CANCELED" for item in by_type.get(item_type, [])) for item_type in replay_types):
        return False

    latest_recovery_plan = next(
        (
            item
            for item in reversed(work_items)
            if item.type == "PLAN_DAG"
            and item.status == "DONE"
            and isinstance(item.payload, dict)
            and str(item.payload.get("recovery_action") or "") == "goal_recovery_retry"
        ),
        None,
    )
    if latest_recovery_plan is None:
        return False

    summary = dict(run.summary or {})
    replayed_sources = summary.get("execution_replay_sources")
    if not isinstance(replayed_sources, list):
        replayed_sources = []
    replayed_source_ids = {
        str(source_id).strip()
        for source_id in replayed_sources
        if str(source_id).strip()
    }
    latest_recovery_id = str(latest_recovery_plan.id)
    if latest_recovery_id in replayed_source_ids:
        return False

    predecessor_id: uuid.UUID | None = latest_recovery_plan.id
    created: list[WorkItem] = []
    for item_type in replay_types:
        template = next((item for item in reversed(by_type.get(item_type, [])) if item.status == "CANCELED"), None)
        if template is None:
            continue
        payload = dict(template.payload or {})
        payload["recovery_action"] = "replay_execution_after_plan_recovery"
        payload["recovery_source_id"] = latest_recovery_id
        replay = WorkItem(
            project_id=run.project_id,
            tenant_id=run.tenant_id,
            run_id=run.id,
            type=template.type,
            key=f"{template.key or template.type}_REPLAY_{uuid.uuid4().hex[:4]}",
            status="QUEUED",
            priority=max(template.priority, 1),
            executor=template.executor,
            attempt=0,
            max_attempts=max(template.max_attempts, 1),
            required_capabilities=list(template.required_capabilities or []),
            payload=payload,
            depends_on_count=1 if predecessor_id else 0,
        )
        session.add(replay)
        await session.flush()
        await link_run_to_work_item(session, replay)
        if predecessor_id:
            session.add(
                WorkItemEdge(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    from_work_item_id=predecessor_id,
                    to_work_item_id=replay.id,
                )
            )
        predecessor_id = replay.id
        created.append(replay)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=replay.id,
            event_type="WORK_ITEM_CREATED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            payload={
                "work_item_id": str(replay.id),
                "type": replay.type,
                "reason": "replay_execution_after_plan_recovery",
            },
        )

    if not created:
        return False

    summary["execution_replay"] = {
        "reason": "plan_recovery_completed_before_execution",
        "source_work_item_id": latest_recovery_id,
        "created_work_item_ids": [str(item.id) for item in created],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    replayed_source_ids.add(latest_recovery_id)
    summary["execution_replay_sources"] = sorted(replayed_source_ids)
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_EXECUTION_REPLAY_QUEUED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "reason": "plan_recovery_completed_before_execution",
            "source_work_item_id": latest_recovery_id,
            "created_work_item_ids": [str(item.id) for item in created],
        },
    )
    return True


async def _requeue_execution_after_backend_recovery(session, run: Run) -> bool:
    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id)
            .order_by(WorkItem.created_at.asc())
        )
    ).scalars().all()
    if not work_items:
        return False

    by_type: dict[str, list[WorkItem]] = {}
    for item in work_items:
        by_type.setdefault(item.type, []).append(item)

    backend_stages = [
        "GENERATE_ROUTE",
        "GENERATE_SERVICE",
        "GENERATE_REPOSITORY",
        "GENERATE_CAPABILITY_BINDING",
    ]
    validation_stages = ["WRITE_TESTS", "REVIEW_DIFF", "RUN_TESTS", "REVIEW_INTEGRATION"]

    latest_backend_recovery = next(
        (
            item
            for item in reversed(work_items)
            if item.type in backend_stages
            and item.status == "DONE"
            and isinstance(item.payload, dict)
            and str(item.payload.get("recovery_action") or "") in {
                "goal_recovery_retry",
                "replay_execution_after_plan_recovery",
                "replay_execution_after_backend_recovery",
            }
        ),
        None,
    )
    if latest_backend_recovery is None:
        return False

    source_stage_index = backend_stages.index(latest_backend_recovery.type)
    replay_types = backend_stages[source_stage_index + 1 :] + validation_stages
    if not replay_types:
        return False

    has_live_replay_types = any(
        any(item.status in {"QUEUED", "RUNNING", "CLAIMED"} for item in by_type.get(item_type, []))
        for item_type in replay_types
    )
    if has_live_replay_types:
        return False
    if not any(any(item.status == "CANCELED" for item in by_type.get(item_type, [])) for item_type in replay_types):
        return False

    summary = dict(run.summary or {})
    replayed_sources = summary.get("execution_replay_sources")
    if not isinstance(replayed_sources, list):
        replayed_sources = []
    replayed_source_ids = {str(source_id).strip() for source_id in replayed_sources if str(source_id).strip()}
    latest_recovery_id = str(latest_backend_recovery.id)
    replay_marker = f"backend:{latest_recovery_id}"
    if replay_marker in replayed_source_ids:
        return False

    predecessor_id: uuid.UUID | None = latest_backend_recovery.id
    created: list[WorkItem] = []
    for item_type in replay_types:
        template = next((item for item in reversed(by_type.get(item_type, [])) if item.status == "CANCELED"), None)
        if template is None:
            continue
        payload = dict(template.payload or {})
        payload["recovery_action"] = "replay_execution_after_backend_recovery"
        payload["recovery_source_id"] = latest_recovery_id
        replay = WorkItem(
            project_id=run.project_id,
            tenant_id=run.tenant_id,
            run_id=run.id,
            type=template.type,
            key=f"{template.key or template.type}_REPLAY_{uuid.uuid4().hex[:4]}",
            status="QUEUED",
            priority=max(template.priority, 1),
            executor=template.executor,
            attempt=0,
            max_attempts=max(template.max_attempts, 1),
            required_capabilities=list(template.required_capabilities or []),
            payload=payload,
            depends_on_count=1 if predecessor_id else 0,
        )
        session.add(replay)
        await session.flush()
        await link_run_to_work_item(session, replay)
        if predecessor_id:
            session.add(
                WorkItemEdge(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    from_work_item_id=predecessor_id,
                    to_work_item_id=replay.id,
                )
            )
        predecessor_id = replay.id
        created.append(replay)
        await record_event(
            session,
            project_id=run.project_id,
            run_id=run.id,
            work_item_id=replay.id,
            event_type="WORK_ITEM_CREATED",
            actor_type="SYSTEM",
            tenant_id=run.tenant_id,
            payload={
                "work_item_id": str(replay.id),
                "type": replay.type,
                "reason": "replay_execution_after_backend_recovery",
            },
        )

    if not created:
        return False

    summary["execution_replay"] = {
        "reason": "backend_recovery_completed_with_canceled_descendants",
        "source_work_item_id": latest_recovery_id,
        "created_work_item_ids": [str(item.id) for item in created],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    replayed_source_ids.add(replay_marker)
    summary["execution_replay_sources"] = sorted(replayed_source_ids)
    run.summary = summary
    session.add(run)
    await record_event(
        session,
        project_id=run.project_id,
        run_id=run.id,
        event_type="RUN_EXECUTION_REPLAY_QUEUED",
        actor_type="SYSTEM",
        tenant_id=run.tenant_id,
        payload={
            "reason": "backend_recovery_completed_with_canceled_descendants",
            "source_work_item_id": latest_recovery_id,
            "created_work_item_ids": [str(item.id) for item in created],
        },
    )
    return True


async def tick(session):
    settings = get_settings()

    await reclaim_expired_work_items(session)
    await reclaim_orphaned_work_items(session)

    # finalize runs
    runs = (
        await session.execute(
            select(Run).where(Run.status.in_(["RUNNING", "QUEUED", "PAUSED"]))
        )
    ).scalars().all()
    from app.services.state_guard import update_run_status
    for run in runs:
        if str(run.status or "").upper() == "PAUSED":
            await _maybe_auto_resume_stall_paused_run(session, run)
            continue
        await _normalize_topology_planning_capability_requirements(session, run)

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
                ok = await _mark_run_failed(session, run, reason="review_diff_rejected")
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
        await _maybe_emit_run_spend_warning(session, run)
        if await _pause_run_for_spend_guard(session, run):
            continue
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
        if queued and active == 0 and not runnable_items and failed_non_superseded and not recovery_pending:
            canceled_count = await _cancel_terminally_blocked_items(session, run)
            if canceled_count:
                await record_event(
                    session,
                    project_id=run.project_id,
                    run_id=run.id,
                    event_type="RUN_DAG_STARVATION_RESOLVED",
                    actor_type="SYSTEM",
                    tenant_id=run.tenant_id,
                    payload={
                        "queued_count": int(queued),
                        "failed_non_superseded": int(failed_non_superseded),
                        "canceled_count": int(canceled_count),
                        "strategy": "cancel_blocked_then_recover",
                    },
                    message="Queued graph starvation resolved by canceling blocked descendants of failed ancestors.",
                )
                # Let the normal failed/recovery flow re-evaluate immediately.
                continue

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
        # If we already have terminal blocking failures and no recovery pending, do not
        # classify the run as "stalled"; downstream queued work is expected to be blocked.
        if queued and active == 0 and not (failed_non_superseded and not recovery_pending):
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
                    if settings.runtime_never_fail_runs:
                        ok = await _finalize_run_degraded(session, run, reason="stalled_no_active_workers")
                        if not ok:
                            continue
                    else:
                        await _cancel_terminally_blocked_items(session, run)
                        await _mark_run_failed(session, run, reason="stalled_no_active_workers")
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

                if settings.runtime_never_fail_runs:
                    ok = await _finalize_run_degraded(session, run, reason="stalled_no_progress")
                    if not ok:
                        continue
                else:
                    await _cancel_terminally_blocked_items(session, run)
                    await _mark_run_failed(session, run, reason="stalled_no_progress")
                continue

        if failed_non_superseded and active == 0 and queued and not recovery_pending:
            runnable_queued = len(runnable_items)
            if runnable_queued == 0:
                canceled_count = await _cancel_terminally_blocked_items(session, run)
                if canceled_count:
                    queued = 0

        if failed_non_superseded and active == 0 and queued == 0 and not recovery_pending:
            if await _auto_decompose_operator_confirmation(session, run, failed_items=failed_items):
                continue
            if await _pause_run_for_budget(session, run, failed_items=failed_items):
                continue
            if await _pause_run_for_operator_confirmation(session, run, failed_items=failed_items):
                continue
            if await _pause_run_for_patch_scope(session, run, failed_items=failed_items):
                continue
            if await _pause_run_for_fix_patch_apply_loop(session, run):
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
                ok = await _mark_run_failed(session, run, reason="goal_concluded_unresolvable")
                if not ok:
                    continue
        elif failed_non_superseded == 0 and active == 0 and queued == 0:
            if await _requeue_execution_after_plan_recovery(session, run):
                continue
            if await _requeue_execution_after_backend_recovery(session, run):
                continue
            if await _requeue_validation_after_recovery(session, run):
                continue
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
                terminal_quality, counts = await _classify_terminal_quality(session, locked)
                summary.pop("degraded_completion", None)
                summary.pop("degraded_reason", None)
                summary.pop("degraded_at", None)
                summary["terminal_quality"] = terminal_quality
                summary["terminal_counts"] = counts
            locked.summary = summary
            session.add(locked)
            await _sync_task_status_for_terminal_run(session, locked, run_status=final_status)
            if final_status == "COMPLETED":
                await record_event(
                    session,
                    project_id=locked.project_id,
                    run_id=locked.id,
                    event_type="RUN_TERMINAL_CLASSIFIED",
                    actor_type="SYSTEM",
                    tenant_id=locked.tenant_id,
                    payload={
                        "terminal_quality": summary.get("terminal_quality", "COMPLETED_CLEAN"),
                        "terminal_counts": summary.get("terminal_counts", {}),
                    },
                )
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
