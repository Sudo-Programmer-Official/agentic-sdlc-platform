from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Run, Trace, WorkItem, WorkItemEdge
from app.runtime.run_state import RetryState
from app.runtime.runtime_recovery_service import RuntimeRecoveryService
from app.services.event_log import record_event
from app.services.runtime_lineage import link_run_to_work_item


RECOVERY_TIER_BY_FAILURE_CLASS: dict[str, str] = {
    "clone_auth_failure": "deterministic",
    "environment_failure": "deterministic",
    "transient": "cheap_recovery",
    "syntax_failure": "code_repair",
    "dependency_failure": "code_repair",
    "test_assertion_failure": "code_repair",
    "test_failure": "code_repair",
    "policy_failure": "architectural_recovery",
    "multi_file_behavior_failure": "architectural_recovery",
    "missing_context": "architectural_recovery",
    "logic_failure": "architectural_recovery",
    "budget_exhausted": "deterministic",
    "fix_applied": "deterministic",
    "patch_apply_failure": "cheap_recovery",
    "output_contract_invalid": "cheap_recovery",
}


@dataclass(frozen=True)
class RecoveryRule:
    when_status: str
    failure_class: str
    action: str
    spawn_type: str | None = None


RECOVERY_POLICIES: dict[str, dict[str, Any]] = {
    "CODE_FRONTEND": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "design_token_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "CODE_BACKEND": {
        "max_retries": 3,
        "rules": (
            RecoveryRule("FAILED", "patch_apply_failure", "retry"),
            RecoveryRule("FAILED", "output_contract_invalid", "retry"),
            RecoveryRule("FAILED", "patch_size_violation", "retry"),
            RecoveryRule("FAILED", "transient", "retry"),
        ),
    },
    "RUN_TESTS": {
        "max_retries": 2,
        "rules": (
            RecoveryRule("FAILED", "transient", "retry"),
            RecoveryRule("FAILED", "syntax_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "dependency_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
            RecoveryRule("FAILED", "test_assertion_failure", "spawn_fix_node", "FIX_TEST_FAILURE"),
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

RECOVERY_TERMINAL_STATUSES = {"QUEUED", "RUNNING", "CLAIMED"}
MAX_SAME_FAILURE_SIGNATURE_RETRIES = 2


def _unique_paths(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


def _coerce_path_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return _unique_paths([item for item in value if isinstance(item, str) and item.strip()])


def _looks_like_test_path(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return False
    pure = PurePosixPath(normalized)
    name = pure.name.lower()
    return (
        any(part.lower() == "tests" for part in pure.parts)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def _fix_recovery_scope(payload: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if not isinstance(payload, dict):
        return [], []
    implementation_files = _coerce_path_list(payload.get("related_files"))
    if not implementation_files:
        implementation_files = [
            path
            for path in _coerce_path_list(payload.get("expected_files"))
            if not _looks_like_test_path(path)
        ]
    failing_test_files = _coerce_path_list(payload.get("target_files"))
    if not failing_test_files:
        failing_test_files = [
            path
            for path in _coerce_path_list(payload.get("expected_files"))
            if _looks_like_test_path(path)
        ]
    return _unique_paths(implementation_files), _unique_paths(failing_test_files)


def _error_text(work_item: WorkItem) -> str:
    bits = [
        work_item.last_error or "",
        str((work_item.result or {}).get("stderr") or ""),
        str((work_item.result or {}).get("stdout") or ""),
        str((work_item.result or {}).get("message") or ""),
    ]
    return "\n".join(bits).lower()


def recovery_tier_for_failure(failure_class: str) -> str:
    return RECOVERY_TIER_BY_FAILURE_CLASS.get(failure_class, "architectural_recovery")


def classify_failure(work_item: WorkItem) -> str:
    if work_item.type == "FIX_TEST_FAILURE" and work_item.status == "DONE":
        return "fix_applied"
    if work_item.type == "REVIEW_DIFF" and work_item.status == "FAILED":
        return "policy_failure"

    text = _error_text(work_item)
    if "run_budget_exhausted" in text or "budget_exhausted" in text:
        return "budget_exhausted"
    if any(
        token in text
        for token in (
            "host key verification failed",
            "could not read from remote repository",
            "github runtime clone auth is unavailable",
            "repository not found",
            "permission denied (publickey)",
            "auth_mode=ssh",
            "auth_mode=github_app",
        )
    ):
        return "clone_auth_failure"
    if any(
        token in text
        for token in (
            "no such file or directory",
            "command not found",
            "executable not found",
            "could not resolve hostname",
        )
    ):
        return "environment_failure"
    if any(
        token in text
        for token in (
            "syntaxerror",
            "indentationerror",
            "nameerror",
            "importerror",
            "modulenotfounderror",
            "error collecting",
        )
    ):
        return "syntax_failure"
    if any(token in text for token in ("cannot import name", "no module named", "missing dependency")):
        return "dependency_failure"
    if any(token in text for token in ("timeout", "temporarily unavailable", "connection reset", "network")):
        return "transient"
    if "model_call_failed" in text:
        return "transient"
    if any(
        token in text
        for token in (
            "patch repair output was invalid",
            "output_contract_invalid",
            "unterminated string starting at",
        )
    ):
        return "output_contract_invalid"
    if any(
        token in text
        for token in (
            "patch apply error",
            "patch apply failed",
            "patch check failed",
            "patch does not apply",
            "error: patch failed:",
            "corrupt patch",
            "patch fragment without header",
        )
    ):
        return "patch_apply_failure"
    if "patch too large for" in text:
        return "patch_size_violation"
    if "ad-hoc hex color" in text and "is not in token_registry.colors" in text:
        return "design_token_violation"
    if work_item.type == "RUN_TESTS" and work_item.status == "FAILED" and "failed " in text:
        return "test_assertion_failure"
    if work_item.type == "RUN_TESTS" and work_item.status == "FAILED":
        return "test_failure"
    if any(token in text for token in ("file not found", "missing document", "missing graph", "not found")):
        return "missing_context"
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


def _is_recovery_work_item(work_item: WorkItem) -> bool:
    if work_item.type == "FIX_TEST_FAILURE":
        return True
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    return any(key in payload for key in ("recovery_source_id", "failed_work_item_id", "recovery_action"))


def _next_same_signature_count(
    *,
    prior_signature: str,
    current_signature: str,
    prior_count: int,
) -> int:
    if not prior_signature or not current_signature or prior_signature != current_signature:
        return 0
    return max(0, int(prior_count)) + 1


async def has_pending_recovery_work(session: AsyncSession, run_id: uuid.UUID) -> bool:
    items = (
        await session.execute(
            select(WorkItem).where(
                WorkItem.run_id == run_id,
                WorkItem.status.in_(list(RECOVERY_TERMINAL_STATUSES)),
            )
        )
    ).scalars().all()
    return any(_is_recovery_work_item(item) for item in items)


async def sync_run_recovery_latch(session: AsyncSession, run_id: uuid.UUID) -> bool:
    pending = await has_pending_recovery_work(session, run_id)
    run = await session.get(Run, run_id)
    if run is None:
        return pending
    summary = dict(run.summary or {})
    summary["recovery_in_progress"] = pending
    if not pending:
        summary["pending_recovery_count"] = 0
    run.summary = summary
    session.add(run)
    await session.flush()
    return pending


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
            "recovery_tier": recovery_tier_for_failure(failure_class),
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

    implementation_files, failing_test_files = _fix_recovery_scope(failed_work_item.payload or {})
    fix_payload = {
        "test_exit_code": (failed_work_item.result or {}).get("exit_code"),
        "stdout": (failed_work_item.result or {}).get("stdout"),
        "stderr": (failed_work_item.result or {}).get("stderr"),
        "failed_work_item_id": str(failed_work_item.id),
        "failure_class": failure_class,
        "recovery_action": "spawn_fix_node",
        "recovery_tier": recovery_tier_for_failure(failure_class),
    }
    if implementation_files:
        fix_payload["target_files"] = implementation_files
        fix_payload["files"] = implementation_files
        fix_payload["expected_files"] = implementation_files
    if failing_test_files:
        fix_payload["related_files"] = failing_test_files
        fix_payload["failing_test_files"] = failing_test_files

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
        payload=fix_payload,
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
    run = await session.get(Run, failed_work_item.run_id)
    if run is not None:
        summary = dict(run.summary or {})
        summary["recovery_in_progress"] = True
        summary["pending_recovery_count"] = int(summary.get("pending_recovery_count") or 0) + 1
        run.summary = summary
        session.add(run)
        await session.flush()
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

    latest_failed = max(
        failed_tests,
        key=lambda item: item.created_at,
    )
    retry_payload = dict(latest_failed.payload or {})
    retry_payload.update(
        {
            "recovery_source_id": str(source_work_item.id),
            "recovery_action": "spawn_retry_node",
        }
    )
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
        payload=retry_payload,
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
    run = await session.get(Run, source_work_item.run_id)
    if run is not None:
        summary = dict(run.summary or {})
        summary["recovery_in_progress"] = True
        summary["pending_recovery_count"] = int(summary.get("pending_recovery_count") or 0) + 1
        run.summary = summary
        session.add(run)
        await session.flush()
    return {"work_item_id": test.id, "type": test.type}


async def maybe_apply_recovery(session: AsyncSession, work_item: WorkItem) -> dict[str, Any] | None:
    runtime_recovery = RuntimeRecoveryService(session)
    failure_class = classify_failure(work_item)
    rule = plan_recovery(work_item, failure_class)
    if not rule:
        return None
    stable_failure_type = runtime_recovery.classify_failure_type(failure_class)
    run = await session.get(Run, work_item.run_id)
    if run is None:
        return None

    await runtime_recovery.emit_classified_event(work_item, stable_failure_type)
    prior_attempts = int(work_item.result.get("recovery_attempts", 0)) if isinstance(work_item.result, dict) else 0
    recovery_action, failure_signature = await runtime_recovery.select_recovery_action_with_memory(
        work_item,
        rule_action=rule.action,
        failure_type=stable_failure_type,
        attempt_number=prior_attempts + 1,
    )
    payload = work_item.payload if isinstance(work_item.payload, dict) else {}
    repository_state = str(payload.get("repository_state") or "").strip().upper()
    if (
        failure_class == "patch_size_violation"
        and repository_state in {"GENESIS", "EARLY_BUILD"}
    ):
        recovery_action = "retry_with_write_file"
    prior_signature = str((work_item.result or {}).get("failure_signature") or "") if isinstance(work_item.result, dict) else ""
    prior_signature_count = int((work_item.result or {}).get("same_failure_signature_count") or 0) if isinstance(work_item.result, dict) else 0
    same_signature_count = _next_same_signature_count(
        prior_signature=prior_signature,
        current_signature=failure_signature,
        prior_count=prior_signature_count,
    )
    if prior_attempts >= 1 and prior_signature and prior_signature == failure_signature:
        switched_action: str | None = None
        if failure_signature.startswith("validation_drift:design_token_missing:"):
            switched_action = "retry_with_design_token_normalization"
        elif failure_signature.startswith("scope_violation:patch_too_large:"):
            switched_action = "retry_with_write_file"
        if switched_action and switched_action != recovery_action:
            recovery_action = switched_action
            await record_event(
                session,
                project_id=work_item.project_id,
                run_id=work_item.run_id,
                work_item_id=work_item.id,
                event_type="RUN_CONVERGENCE_STRATEGY_SWITCHED",
                actor_type="SYSTEM",
                tenant_id=work_item.tenant_id,
                payload={
                    "work_item_id": str(work_item.id),
                    "failure_signature": failure_signature,
                    "previous_action": rule.action,
                    "new_action": recovery_action,
                    "reason": "repeated_failure_signature",
                },
            )
    if same_signature_count >= MAX_SAME_FAILURE_SIGNATURE_RETRIES:
        _merge_result_metadata(
            work_item,
            failure_class=failure_class,
            failure_type=stable_failure_type,
            recovery_action="escalate_to_human",
            failure_signature=failure_signature,
            same_failure_signature_count=same_signature_count,
            retry_state=RetryState.EXHAUSTED,
            recovery_exhausted_reason="repeated_failure_signature",
            suggested_next_action="Adjust scope, contract/tokens, or strategy before rerunning.",
        )
        session.add(work_item)
        await session.flush()
        await record_event(
            session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RUN_CONVERGENCE_STOPPED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={
                "work_item_id": str(work_item.id),
                "failure_signature": failure_signature,
                "same_failure_signature_count": same_signature_count,
                "threshold": MAX_SAME_FAILURE_SIGNATURE_RETRIES,
                "reason": "repeated_failure_signature",
            },
            message="Recovery halted: repeated identical failure signature exceeded convergence threshold.",
        )
        await runtime_recovery.emit_escalated_event(work_item, reason="repeated_failure_signature")
        await sync_run_recovery_latch(session, work_item.run_id)
        return {"action": "escalate_to_human", "reason": "repeated_failure_signature"}
    await runtime_recovery.emit_action_selected_event(work_item, recovery_action)
    budget_decision = await runtime_recovery.check_budget(run, work_item, stable_failure_type)
    if not budget_decision.allowed:
        _merge_result_metadata(
            work_item,
            failure_class=failure_class,
            failure_type=stable_failure_type,
            recovery_action="escalate_to_human",
            failure_signature=failure_signature,
            same_failure_signature_count=same_signature_count,
            retry_state=RetryState.EXHAUSTED,
            recovery_exhausted_reason=budget_decision.reason,
            suggested_next_action="Review failure evidence and continue manually.",
        )
        session.add(work_item)
        await session.flush()
        await runtime_recovery.emit_escalated_event(work_item, reason=f"recovery_budget_exhausted:{budget_decision.reason}")
        return {"action": "escalate_to_human", "reason": budget_decision.reason}

    _merge_result_metadata(
        work_item,
        failure_class=failure_class,
        failure_type=stable_failure_type,
        failure_signature=failure_signature,
        recovery_action=recovery_action,
        recovery_tier=recovery_tier_for_failure(failure_class),
        retry_state="PENDING",
        recovery_attempts=prior_attempts + 1,
        same_failure_signature_count=same_signature_count,
    )
    session.add(work_item)
    await session.flush()
    recovery_attempt = await runtime_recovery.create_attempt(
        run=run,
        work_item=work_item,
        failure_type=stable_failure_type,
        recovery_action=recovery_action,
        rationale=f"class={failure_class}, rule={rule.action}",
    )

    outcome: dict[str, Any] | None = None
    if rule.action == "retry":
        if work_item.attempt + 1 >= work_item.max_attempts:
            _merge_result_metadata(work_item, retry_state=RetryState.EXHAUSTED)
            session.add(work_item)
            await session.flush()
        else:
            payload = dict(work_item.payload or {})
            if failure_class == "output_contract_invalid":
                payload["strict_output_contract_mode"] = True
                payload["prior_output_contract_failures"] = int(payload.get("prior_output_contract_failures") or 0) + 1
            payload["recovery_action"] = recovery_action
            if recovery_action == "retry_with_write_file":
                payload["recovery_strategy"] = "write_file_preferred"
                payload["recovery_reason"] = "patch_apply_failed"
            elif recovery_action == "retry_with_smaller_patch":
                payload["recovery_strategy"] = "minimal_patch_preferred"
                payload["recovery_reason"] = "patch_apply_failed"
            elif recovery_action == "retry_with_design_token_normalization":
                payload["recovery_strategy"] = "design_token_auto_normalize"
                payload["recovery_reason"] = "design_token_missing"
            elif recovery_action == "refresh_context":
                payload["recovery_strategy"] = "refresh_context"
            work_item.payload = payload
            work_item.status = "QUEUED"
            work_item.attempt += 1
            work_item.assigned_agent_id = None
            work_item.lease_expires_at = None
            work_item.finished_at = None
            _merge_result_metadata(work_item, retry_state=RetryState.PENDING)
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
            if recovery_action == "retry_with_write_file":
                await record_event(
                    session,
                    project_id=work_item.project_id,
                    run_id=work_item.run_id,
                    work_item_id=work_item.id,
                    event_type="PATCH_STRATEGY_SWITCHED_TO_WRITE_FILE",
                    actor_type="SYSTEM",
                    tenant_id=work_item.tenant_id,
                    payload={"work_item_id": str(work_item.id), "reason": "patch_apply_failed"},
                )
            outcome = {"action": "retry", "work_item_id": work_item.id}

    elif rule.action == "spawn_fix_node":
        _merge_result_metadata(work_item, retry_state=RetryState.PENDING)
        session.add(work_item)
        await session.flush()
        created = await _spawn_fix_node(session, work_item, failure_class)
        outcome = {"action": rule.action, "created": created}

    elif rule.action == "spawn_retry_node":
        _merge_result_metadata(work_item, retry_state=RetryState.PENDING)
        session.add(work_item)
        await session.flush()
        created = await _spawn_test_retry(session, work_item)
        outcome = {"action": rule.action, "created": created}

    elif rule.action == "block_run":
        _merge_result_metadata(work_item, retry_state=RetryState.BLOCKED)
        session.add(work_item)
        await session.flush()
        await _emit_recovery_event(
            session,
            work_item,
            failure_class=failure_class,
            action="block_run",
            message=f"{work_item.type} requires manual review; auto-healing blocked.",
        )
        outcome = {"action": "block_run"}

    succeeded = bool(outcome and (outcome.get("action") != "block_run"))
    await runtime_recovery.complete_attempt(
        recovery_attempt,
        succeeded=succeeded,
        rationale=(None if succeeded else "No automatic recovery outcome produced."),
    )
    await runtime_recovery.record_memory_outcome(
        work_item=work_item,
        failure_type=stable_failure_type,
        failure_signature=failure_signature,
        recovery_action=recovery_action,
        succeeded=succeeded,
        attempt_number=recovery_attempt.attempt_number,
    )
    await runtime_recovery.emit_attempt_terminal_event(work_item, recovery_attempt, succeeded=succeeded)
    if not succeeded:
        await runtime_recovery.emit_escalated_event(work_item, reason="recovery_action_not_effective")

    await sync_run_recovery_latch(session, work_item.run_id)
    return outcome
