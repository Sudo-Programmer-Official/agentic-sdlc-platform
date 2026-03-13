from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Trace, WorkItem, WorkItemEdge
from app.services.event_log import record_event
from app.services.runtime_lineage import link_run_to_work_item


@dataclass(frozen=True)
class RecoveryRule:
    when_status: str
    failure_class: str
    action: str
    spawn_type: str | None = None


RECOVERY_POLICIES: dict[str, dict[str, Any]] = {
    "RUN_TESTS": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("FAILED", "transient", "retry"),
            RecoveryRule("FAILED", "test_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
        ),
    },
    "FIX_TEST_FAILURE": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("DONE", "fix_applied", "spawn_retry_node", "RUN_TESTS"),
        ),
    },
    "REVIEW_DIFF": {
        "max_retries": 0,
        "rules": (
            RecoveryRule("FAILED", "policy_failure", "block_run"),
        ),
    },
}


def _error_text(work_item: WorkItem) -> str:
    bits = [
        work_item.last_error or "",
        str((work_item.result or {}).get("stderr") or ""),
        str((work_item.result or {}).get("stdout") or ""),
        str((work_item.result or {}).get("message") or ""),
    ]
    return "\n".join(bits).lower()


def classify_failure(work_item: WorkItem) -> str:
    if work_item.type == "FIX_TEST_FAILURE" and work_item.status == "DONE":
        return "fix_applied"
    if work_item.type == "REVIEW_DIFF" and work_item.status == "FAILED":
        return "policy_failure"

    text = _error_text(work_item)
    if any(token in text for token in ("timeout", "temporarily unavailable", "connection reset", "network")):
        return "transient"
    if any(token in text for token in ("file not found", "missing document", "missing graph", "not found")):
        return "missing_context"
    if work_item.type == "RUN_TESTS" and work_item.status == "FAILED":
        return "test_failure"
    return "logic_failure"


def plan_recovery(work_item: WorkItem, failure_class: str) -> RecoveryRule | None:
    policy = RECOVERY_POLICIES.get(work_item.type)
    if not policy:
        return None
    for rule in policy["rules"]:
        if rule.when_status == work_item.status and rule.failure_class == failure_class:
            return rule
    return None


def _merge_result_metadata(work_item: WorkItem, **updates: Any) -> None:
    payload = dict(work_item.result or {})
    payload.update({key: value for key, value in updates.items() if value is not None})
    work_item.result = payload


async def _emit_recovery_event(
    session: AsyncSession,
    work_item: WorkItem,
    *,
    failure_class: str,
    action: str,
    recovery_work_item_id: uuid.UUID | None = None,
    recovery_type: str | None = None,
    message: str | None = None,
) -> None:
    await record_event(
        session,
        project_id=work_item.project_id,
        run_id=work_item.run_id,
        work_item_id=work_item.id,
        event_type="WORK_ITEM_RECOVERY",
        actor_type="SYSTEM",
        message=message,
        payload={
            "work_item_id": str(work_item.id),
            "failure_class": failure_class,
            "recovery_action": action,
            "recovery_work_item_id": str(recovery_work_item_id) if recovery_work_item_id else None,
            "recovery_type": recovery_type,
        },
        tenant_id=work_item.tenant_id,
    )


async def _spawn_fix_node(session: AsyncSession, failed_work_item: WorkItem, failure_class: str) -> dict[str, Any] | None:
    settings = get_settings()
    count = (
        await session.execute(
            select(func.count()).where(
                WorkItem.run_id == failed_work_item.run_id,
                WorkItem.type == "FIX_TEST_FAILURE",
            )
        )
    ).scalar() or 0
    if count >= settings.max_fix_attempts_per_run:
        return None

    fix = WorkItem(
        project_id=failed_work_item.project_id,
        tenant_id=failed_work_item.tenant_id,
        run_id=failed_work_item.run_id,
        type="FIX_TEST_FAILURE",
        key=f"FIX_TEST_FAILURE_{count + 1}",
        status="QUEUED",
        executor="codex",
        priority=9,
        required_capabilities=["code"],
        payload={
            "test_exit_code": (failed_work_item.result or {}).get("exit_code"),
            "stdout": (failed_work_item.result or {}).get("stdout"),
            "stderr": (failed_work_item.result or {}).get("stderr"),
            "failed_work_item_id": str(failed_work_item.id),
            "failure_class": failure_class,
            "recovery_action": "spawn_fix_node",
        },
    )
    session.add(fix)
    await session.flush()
    await link_run_to_work_item(session, fix)
    session.add(
        Trace(
            tenant_id=failed_work_item.tenant_id,
            project_id=failed_work_item.project_id,
            from_type="work_item",
            from_id=failed_work_item.id,
            to_type="work_item",
            to_id=fix.id,
            relation_type="supersedes",
            relation_strength=1.0,
        )
    )
    await record_event(
        session,
        project_id=fix.project_id,
        run_id=fix.run_id,
        work_item_id=fix.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(fix.id), "type": fix.type},
        tenant_id=fix.tenant_id,
    )
    await _emit_recovery_event(
        session,
        failed_work_item,
        failure_class=failure_class,
        action="spawn_fix_node",
        recovery_work_item_id=fix.id,
        recovery_type=fix.type,
        message=f"Auto recovery queued {fix.type} for failed {failed_work_item.type}.",
    )
    return {"work_item_id": fix.id, "type": fix.type}


async def _spawn_test_retry(session: AsyncSession, source_work_item: WorkItem) -> dict[str, Any] | None:
    failed_tests = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == source_work_item.run_id,
                WorkItem.type == "RUN_TESTS",
                WorkItem.status == "FAILED",
            )
        )
    ).scalars().all()
    if not failed_tests:
        return None

    test = WorkItem(
        project_id=source_work_item.project_id,
        tenant_id=source_work_item.tenant_id,
        run_id=source_work_item.run_id,
        type="RUN_TESTS",
        key=f"RUN_TESTS_{uuid.uuid4().hex[:4]}",
        status="QUEUED",
        executor="test",
        priority=8,
        required_capabilities=["test"],
        payload={
            "recovery_source_id": str(source_work_item.id),
            "recovery_action": "spawn_retry_node",
        },
        depends_on_count=1,
    )
    session.add(test)
    await session.flush()
    await link_run_to_work_item(session, test)
    session.add(
        WorkItemEdge(
            tenant_id=source_work_item.tenant_id,
            run_id=source_work_item.run_id,
            from_work_item_id=source_work_item.id,
            to_work_item_id=test.id,
        )
    )

    for failed in failed_tests:
        outgoing_edges = (
            await session.execute(
                select(WorkItemEdge).where(
                    WorkItemEdge.run_id == failed.run_id,
                    WorkItemEdge.from_work_item_id == failed.id,
                )
            )
        ).scalars().all()
        failed_result = dict(failed.result or {})
        failed_result["superseded"] = True
        failed_result["superseded_by"] = str(test.id)
        failed.result = failed_result
        session.add(failed)
        for edge in outgoing_edges:
            edge.from_work_item_id = test.id
            session.add(edge)
        session.add(
            Trace(
                tenant_id=failed.tenant_id,
                project_id=failed.project_id,
                from_type="work_item",
                from_id=failed.id,
                to_type="work_item",
                to_id=test.id,
                relation_type="supersedes",
                relation_strength=1.0,
            )
        )

    session.add(
        Trace(
            tenant_id=source_work_item.tenant_id,
            project_id=source_work_item.project_id,
            from_type="work_item",
            from_id=source_work_item.id,
            to_type="work_item",
            to_id=test.id,
            relation_type="references",
            relation_strength=1.0,
        )
    )
    await record_event(
        session,
        project_id=test.project_id,
        run_id=test.run_id,
        work_item_id=test.id,
        event_type="WORK_ITEM_CREATED",
        actor_type="SYSTEM",
        payload={"work_item_id": str(test.id), "type": test.type},
        tenant_id=test.tenant_id,
    )
    await _emit_recovery_event(
        session,
        source_work_item,
        failure_class="fix_applied",
        action="spawn_retry_node",
        recovery_work_item_id=test.id,
        recovery_type=test.type,
        message=f"Recovery queued {test.type} retry after {source_work_item.type}.",
    )
    return {"work_item_id": test.id, "type": test.type}


async def maybe_apply_recovery(session: AsyncSession, work_item: WorkItem) -> dict[str, Any] | None:
    failure_class = classify_failure(work_item)
    rule = plan_recovery(work_item, failure_class)
    if not rule:
        return None

    _merge_result_metadata(
        work_item,
        failure_class=failure_class,
        recovery_action=rule.action,
    )
    session.add(work_item)
    await session.flush()

    if rule.action == "retry":
        if work_item.attempt + 1 >= work_item.max_attempts:
            return None
        work_item.status = "QUEUED"
        work_item.attempt += 1
        work_item.assigned_agent_id = None
        work_item.lease_expires_at = None
        work_item.finished_at = None
        session.add(work_item)
        await session.flush()
        await record_event(
            session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="WORK_ITEM_RETRIED",
            actor_type="SYSTEM",
            payload={"work_item_id": str(work_item.id), "attempt": work_item.attempt},
            tenant_id=work_item.tenant_id,
        )
        await _emit_recovery_event(
            session,
            work_item,
            failure_class=failure_class,
            action="retry",
            message=f"Retry queued for {work_item.type} after transient failure.",
        )
        return {"action": "retry", "work_item_id": work_item.id}

    if rule.action == "spawn_fix_node":
        created = await _spawn_fix_node(session, work_item, failure_class)
        return {"action": rule.action, "created": created}

    if rule.action == "spawn_retry_node":
        created = await _spawn_test_retry(session, work_item)
        return {"action": rule.action, "created": created}

    if rule.action == "block_run":
        await _emit_recovery_event(
            session,
            work_item,
            failure_class=failure_class,
            action="block_run",
            message=f"{work_item.type} requires manual review; auto-healing blocked.",
        )
        return {"action": "block_run"}

    return None
