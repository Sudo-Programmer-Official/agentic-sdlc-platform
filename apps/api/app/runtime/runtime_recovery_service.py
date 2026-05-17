from __future__ import annotations

import uuid
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import RecoveryAttempt, RecoveryMemoryProfile, Run, WorkItem
from app.services.event_log import record_event


STABLE_FAILURE_TYPES = {
    "parser_error",
    "patch_apply_failed",
    "test_failed",
    "validation_drift",
    "worker_stalled",
    "auth_failed",
    "scope_violation",
    "preview_failed",
    "push_failed",
    "unknown",
}


STABLE_RECOVERY_ACTIONS = {
    "retry_same_step",
    "retry_with_smaller_patch",
    "retry_with_write_file",
    "refresh_context",
    "fork_run",
    "requeue_work_item",
    "create_fix_task",
    "mark_delivery_manual_required",
    "escalate_to_human",
    "fail_safely",
    "retry_with_design_token_normalization",
}


FAILURE_CLASS_MAP = {
    "syntax_failure": "parser_error",
    "output_contract_invalid": "parser_error",
    "patch_apply_failure": "patch_apply_failed",
    "test_assertion_failure": "test_failed",
    "test_failure": "test_failed",
    "policy_failure": "validation_drift",
    "clone_auth_failure": "auth_failed",
    "environment_failure": "worker_stalled",
    "missing_context": "scope_violation",
    "patch_size_violation": "scope_violation",
    "design_token_violation": "validation_drift",
}


ACTION_MAP = {
    "retry": "retry_same_step",
    "spawn_fix_node": "create_fix_task",
    "spawn_retry_node": "requeue_work_item",
    "block_run": "escalate_to_human",
}


@dataclass
class RecoveryBudgetDecision:
    allowed: bool
    reason: str | None = None


class RuntimeRecoveryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    def classify_failure_type(self, failure_class: str) -> str:
        mapped = FAILURE_CLASS_MAP.get(failure_class, "unknown")
        return mapped if mapped in STABLE_FAILURE_TYPES else "unknown"

    def select_recovery_action(self, rule_action: str, failure_type: str, attempt_number: int) -> str:
        if failure_type == "parser_error":
            if attempt_number == 1:
                return "retry_with_write_file"
            return "refresh_context"
        if failure_type == "patch_apply_failed":
            if attempt_number == 1:
                return "retry_with_smaller_patch"
            if attempt_number == 2:
                return "retry_with_write_file"
            return "refresh_context"
        if failure_type == "scope_violation":
            if attempt_number == 1:
                return "retry_with_write_file"
            return "refresh_context"
        if failure_type == "validation_drift":
            if attempt_number == 1:
                return "retry_with_design_token_normalization"
            return "refresh_context"
        mapped = ACTION_MAP.get(rule_action, "fail_safely")
        return mapped if mapped in STABLE_RECOVERY_ACTIONS else "fail_safely"

    async def select_recovery_action_with_memory(
        self,
        work_item: WorkItem,
        *,
        rule_action: str,
        failure_type: str,
        attempt_number: int,
    ) -> tuple[str, str]:
        default_action = self.select_recovery_action(rule_action, failure_type, attempt_number)
        if not self.settings.runtime_recovery_memory_enabled:
            return default_action, "disabled"
        signature = self.build_failure_signature(work_item, failure_type)
        rows = (
            await self.session.execute(
                select(RecoveryMemoryProfile)
                .where(
                    RecoveryMemoryProfile.tenant_id == work_item.tenant_id,
                    RecoveryMemoryProfile.project_id == work_item.project_id,
                    RecoveryMemoryProfile.failure_signature == signature,
                    RecoveryMemoryProfile.failure_type == failure_type,
                )
                .order_by(RecoveryMemoryProfile.success_rate.desc(), RecoveryMemoryProfile.total_attempts.desc())
            )
        ).scalars().all()
        if not rows:
            await record_event(
                self.session,
                project_id=work_item.project_id,
                run_id=work_item.run_id,
                work_item_id=work_item.id,
                event_type="RECOVERY_MEMORY_MISS",
                actor_type="SYSTEM",
                tenant_id=work_item.tenant_id,
                payload={"failure_signature": signature, "failure_type": failure_type},
            )
            return default_action, signature
        best = rows[0]
        if best.total_attempts < int(self.settings.runtime_recovery_memory_min_samples) or best.success_rate < float(
            self.settings.runtime_recovery_memory_min_success_rate
        ):
            await record_event(
                self.session,
                project_id=work_item.project_id,
                run_id=work_item.run_id,
                work_item_id=work_item.id,
                event_type="RECOVERY_MEMORY_MATCHED",
                actor_type="SYSTEM",
                tenant_id=work_item.tenant_id,
                payload={
                    "failure_signature": signature,
                    "failure_type": failure_type,
                    "recovery_action": best.recovery_action,
                    "success_rate": best.success_rate,
                    "samples": best.total_attempts,
                    "confidence": "low",
                },
            )
            return default_action, signature
        await record_event(
            self.session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RECOVERY_MEMORY_MATCHED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={
                "failure_signature": signature,
                "failure_type": failure_type,
                "recovery_action": best.recovery_action,
                "success_rate": best.success_rate,
                "samples": best.total_attempts,
                "confidence": "high",
            },
        )
        if best.recovery_action != default_action:
            await record_event(
                self.session,
                project_id=work_item.project_id,
                run_id=work_item.run_id,
                work_item_id=work_item.id,
                event_type="RECOVERY_POLICY_OVERRIDDEN_BY_MEMORY",
                actor_type="SYSTEM",
                tenant_id=work_item.tenant_id,
                payload={
                    "failure_signature": signature,
                    "failure_type": failure_type,
                    "policy_action": default_action,
                    "memory_action": best.recovery_action,
                    "success_rate": best.success_rate,
                },
            )
            return best.recovery_action, signature
        return default_action, signature

    async def emit_classified_event(self, work_item: WorkItem, failure_type: str) -> None:
        await record_event(
            self.session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RECOVERY_CLASSIFIED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={"failure_type": failure_type},
        )

    async def emit_action_selected_event(self, work_item: WorkItem, recovery_action: str) -> None:
        await record_event(
            self.session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RECOVERY_ACTION_SELECTED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={"recovery_action": recovery_action},
        )

    async def _attempt_count(
        self,
        *,
        run_id: uuid.UUID,
        work_item_id: uuid.UUID | None = None,
        failure_type: str | None = None,
    ) -> int:
        where = [RecoveryAttempt.run_id == run_id]
        if work_item_id is not None:
            where.append(RecoveryAttempt.work_item_id == work_item_id)
        if failure_type is not None:
            where.append(RecoveryAttempt.failure_type == failure_type)
        count = (await self.session.execute(select(func.count()).where(*where))).scalar()
        return int(count or 0)

    async def _run_cost_estimate(self, run: Run) -> float:
        summary = run.summary if isinstance(run.summary, dict) else {}
        contract = summary.get("execution_contract") if isinstance(summary.get("execution_contract"), dict) else {}
        budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
        return float(budget.get("used_cost_cents") or 0.0)

    async def check_budget(self, run: Run, work_item: WorkItem, failure_type: str) -> RecoveryBudgetDecision:
        max_work_item = max(0, int(self.settings.runtime_recovery_max_attempts_per_work_item))
        max_failure_type = max(0, int(self.settings.runtime_recovery_max_attempts_per_failure_type))
        max_run = max(0, int(self.settings.runtime_recovery_max_attempts_per_run))
        max_runtime_minutes = max(0, int(self.settings.runtime_recovery_max_runtime_minutes))
        max_cost_estimate = max(0.0, float(self.settings.runtime_recovery_max_cost_estimate_cents))

        work_item_attempts = await self._attempt_count(run_id=run.id, work_item_id=work_item.id)
        if work_item_attempts >= max_work_item:
            return RecoveryBudgetDecision(False, "max_attempts_per_work_item")

        failure_attempts = await self._attempt_count(run_id=run.id, failure_type=failure_type)
        if failure_attempts >= max_failure_type:
            return RecoveryBudgetDecision(False, "max_attempts_per_failure_type")

        run_attempts = await self._attempt_count(run_id=run.id)
        if run_attempts >= max_run:
            return RecoveryBudgetDecision(False, "max_attempts_per_run")

        now = datetime.now(timezone.utc)
        started = run.started_at or run.created_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed_minutes = (now - started).total_seconds() / 60.0
            if elapsed_minutes >= float(max_runtime_minutes):
                return RecoveryBudgetDecision(False, "max_runtime_minutes")

        used_cost = await self._run_cost_estimate(run)
        if used_cost >= max_cost_estimate:
            return RecoveryBudgetDecision(False, "max_cost_estimate")

        return RecoveryBudgetDecision(True)

    async def create_attempt(
        self,
        *,
        run: Run,
        work_item: WorkItem,
        failure_type: str,
        recovery_action: str,
        rationale: str,
    ) -> RecoveryAttempt:
        attempt_number = (await self._attempt_count(run_id=run.id, work_item_id=work_item.id, failure_type=failure_type)) + 1
        row = RecoveryAttempt(
            tenant_id=work_item.tenant_id,
            project_id=work_item.project_id,
            run_id=run.id,
            work_item_id=work_item.id,
            failure_type=failure_type,
            recovery_action=recovery_action,
            attempt_number=attempt_number,
            result="started",
            rationale=rationale,
        )
        self.session.add(row)
        await self.session.flush()
        await record_event(
            self.session,
            project_id=work_item.project_id,
            run_id=run.id,
            work_item_id=work_item.id,
            event_type="RECOVERY_ATTEMPT_STARTED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={
                "recovery_attempt_id": str(row.id),
                "attempt_number": attempt_number,
                "failure_type": failure_type,
                "recovery_action": recovery_action,
            },
        )
        return row

    async def complete_attempt(self, attempt: RecoveryAttempt, *, succeeded: bool, rationale: str | None = None) -> None:
        attempt.result = "succeeded" if succeeded else "failed"
        if rationale:
            attempt.rationale = rationale
        self.session.add(attempt)
        await self.session.flush()

    async def record_memory_outcome(
        self,
        *,
        work_item: WorkItem,
        failure_type: str,
        failure_signature: str,
        recovery_action: str,
        succeeded: bool,
        attempt_number: int,
    ) -> None:
        if not self.settings.runtime_recovery_memory_enabled:
            return
        row = await self.session.scalar(
            select(RecoveryMemoryProfile).where(
                RecoveryMemoryProfile.tenant_id == work_item.tenant_id,
                RecoveryMemoryProfile.project_id == work_item.project_id,
                RecoveryMemoryProfile.failure_signature == failure_signature,
                RecoveryMemoryProfile.failure_type == failure_type,
                RecoveryMemoryProfile.recovery_action == recovery_action,
            )
        )
        if row is None:
            row = RecoveryMemoryProfile(
                tenant_id=work_item.tenant_id,
                project_id=work_item.project_id,
                failure_signature=failure_signature,
                failure_type=failure_type,
                recovery_action=recovery_action,
                total_attempts=0,
                success_count=0,
                failure_count=0,
                success_rate=0.0,
                average_recovery_attempts=0.0,
            )
        row.total_attempts += 1
        if succeeded:
            row.success_count += 1
        else:
            row.failure_count += 1
        row.success_rate = round(row.success_count / max(1, row.total_attempts), 4)
        prev_avg = float(row.average_recovery_attempts or 0.0)
        row.average_recovery_attempts = round(((prev_avg * (row.total_attempts - 1)) + attempt_number) / row.total_attempts, 3)
        self.session.add(row)
        await self.session.flush()

    async def emit_attempt_terminal_event(self, work_item: WorkItem, attempt: RecoveryAttempt, *, succeeded: bool) -> None:
        await record_event(
            self.session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RECOVERY_ATTEMPT_SUCCEEDED" if succeeded else "RECOVERY_ATTEMPT_FAILED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={
                "recovery_attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "failure_type": attempt.failure_type,
                "recovery_action": attempt.recovery_action,
            },
        )

    async def emit_escalated_event(self, work_item: WorkItem, reason: str) -> None:
        await record_event(
            self.session,
            project_id=work_item.project_id,
            run_id=work_item.run_id,
            work_item_id=work_item.id,
            event_type="RECOVERY_ESCALATED",
            actor_type="SYSTEM",
            tenant_id=work_item.tenant_id,
            payload={"reason": reason, "suggested_next_action": "Review evidence and resolve manually."},
        )
    def build_failure_signature(self, work_item: WorkItem, failure_type: str) -> str:
        text = " ".join(
            [
                str(work_item.type or ""),
                str(work_item.executor or ""),
                str((work_item.result or {}).get("message") or ""),
                str(work_item.last_error or ""),
            ]
        ).strip()
        lowered = text.lower()
        if "ad-hoc hex color" in lowered and "is not in token_registry.colors" in lowered:
            import re

            match = re.search(r"(#[0-9a-fA-F]{3,8})", text)
            hex_value = (match.group(1).lower() if match else "unknown")
            return f"{failure_type}:design_token_missing:{hex_value}"
        if "patch too large for" in lowered:
            import re

            match = re.search(r"patch too large for ([^ )]+)", lowered)
            file_name = (match.group(1).strip() if match else "unknown")
            return f"{failure_type}:patch_too_large:{file_name}"
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] if text else "none"
        return f"{failure_type}:{work_item.type}:{digest}"
