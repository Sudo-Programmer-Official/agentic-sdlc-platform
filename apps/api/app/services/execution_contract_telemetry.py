from __future__ import annotations

from typing import Any

from app.runtime.execution_contract import coerce_execution_contract
from app.schemas.mission_control import (
    MissionControlExecutionBudgetTelemetry,
    MissionControlExecutionContractTelemetry,
)


def build_execution_contract_telemetry(
    summary: dict[str, Any] | None,
) -> MissionControlExecutionContractTelemetry | None:
    if not isinstance(summary, dict):
        return None
    contract = coerce_execution_contract(summary.get("execution_contract"))
    if contract is None:
        return None
    return MissionControlExecutionContractTelemetry(
        lifecycle_state=contract.lifecycle_state,
        validation_state=contract.validation_state,
        retry_state=contract.retry_state,
        scope_mode=contract.scope_mode,
        risk_level=contract.risk_level,
        file_budget=contract.file_budget,
        hard_file_budget=contract.hard_file_budget,
        target_files=list(contract.target_files)[:8],
        allowed_file_count=len(contract.allowed_files),
        protected_paths=list(contract.protected_paths)[:6],
        safe_paths=list(contract.safe_paths)[:6],
        validation_steps=list(contract.validation_steps)[:6],
        allowed_command_prefixes=list(contract.allowed_command_prefixes)[:8],
        build_command=contract.build_command,
        test_command=contract.test_command,
        lint_command=contract.lint_command,
        budget=MissionControlExecutionBudgetTelemetry(
            max_tokens=contract.budget.max_tokens,
            used_tokens=contract.budget.used_tokens,
            remaining_tokens=contract.budget.remaining_tokens,
            max_cost_cents=contract.budget.max_cost_cents,
            used_cost_cents=contract.budget.used_cost_cents,
            remaining_cost_cents=contract.budget.remaining_cost_cents,
            recovery_reserve_cost_cents=contract.budget.recovery_reserve_cost_cents,
            used_recovery_cost_cents=contract.budget.used_recovery_cost_cents,
            remaining_recovery_cost_cents=contract.budget.remaining_recovery_cost_cents,
            active_budget_partition=contract.budget.active_budget_partition,
            budget_mode=contract.budget.budget_mode,
            model_tier_cap=contract.budget.model_tier_cap,
            completion_token_cap=contract.budget.completion_token_cap,
            escalation_reason=contract.budget.escalation_reason,
            last_model_tier=contract.budget.last_model_tier,
            updated_at=contract.budget.updated_at,
        ),
    )
