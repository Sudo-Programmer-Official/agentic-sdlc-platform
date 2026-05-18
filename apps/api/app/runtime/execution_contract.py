from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
import shlex
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Run, WorkItem
from app.runtime.run_state import BudgetMode, ContractLifecycleState, RetryState, ValidationState
from app.services.work_item_state import is_blocking_failure, is_non_blocking_failure, is_superseded_failure

VALIDATION_WORK_ITEM_TYPES = {"WRITE_TESTS", "RUN_TESTS", "REVIEW_DIFF", "REVIEW_INTEGRATION"}
DEFAULT_CONTRACT_VERSION = 1
DEFAULT_CODEX_MAX_RUN_TOKENS = 200_000
DEFAULT_CODEX_MAX_RUN_COST_CENTS = 50.0
DEFAULT_CODEX_MAX_TOKENS = 1_200
DEFAULT_ECONOMY_COMPLETION_TOKENS = 800
DEFAULT_STANDARD_COMPLETION_TOKENS = 1_200
AI_BUDGETED_WORK_ITEM_TYPES = {
    "PLAN_DAG",
    "PLAN_BACKEND_TOPOLOGY",
    "GENERATE_ROUTE",
    "GENERATE_SERVICE",
    "GENERATE_REPOSITORY",
    "GENERATE_CAPABILITY_BINDING",
    "CODE_BACKEND",
    "CODE_FRONTEND",
    "WRITE_TESTS",
    "REVIEW_DIFF",
    "REVIEW_INTEGRATION",
    "FIX_TEST_FAILURE",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return normalized
    pure = PurePosixPath(normalized)
    return "." if str(pure) == "." else str(pure)


def _unique_paths(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        cleaned = _normalize_path(value)
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


def _path_matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_prefix = _normalize_path(prefix)
    if not normalized_path or not normalized_prefix:
        return False
    if normalized_prefix == ".":
        return True
    path_parts = PurePosixPath(normalized_path).parts
    prefix_parts = PurePosixPath(normalized_prefix).parts
    if len(prefix_parts) > len(path_parts):
        return False
    return path_parts[: len(prefix_parts)] == prefix_parts


def _string_list_from_mapping(mapping: dict[str, Any] | None, *keys: str) -> list[str]:
    if not isinstance(mapping, dict):
        return []
    values: list[str] = []
    for key in keys:
        raw = mapping.get(key)
        if isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
        elif isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, str) and item.strip())
    return _unique_paths(values)


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _coerce_command_index(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    commands: dict[str, dict[str, Any]] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(raw, str) and raw.strip():
            commands[key.strip()] = {"command": raw.strip()}
            continue
        if not isinstance(raw, dict):
            continue
        command = raw.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        commands[key.strip()] = {
            "command": command.strip(),
            "kind": raw.get("kind"),
            "label": raw.get("label"),
            "paths": _coerce_string_list(raw.get("paths")),
        }
    return commands


def _prefixes_from_commands(command_index: dict[str, dict[str, Any]]) -> list[str]:
    prefixes: list[str] = []
    for entry in command_index.values():
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.strip().split()
        if tokens:
            prefixes.append(tokens[0])
    return _unique_paths(prefixes)


def _command_matches_scope(command_paths: list[str], scope_paths: list[str]) -> bool:
    if not command_paths or not scope_paths:
        return bool(command_paths) is False
    return any(
        _path_matches_prefix(scope_path, command_path) or _path_matches_prefix(command_path, scope_path)
        for scope_path in scope_paths
        for command_path in command_paths
    )


def _resolve_named_command(
    command_index: dict[str, dict[str, Any]],
    *,
    preferred_keys: list[str],
    kind: str,
    scope_paths: list[str],
) -> str | None:
    for key in preferred_keys:
        entry = command_index.get(key)
        if not isinstance(entry, dict):
            continue
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        paths = _coerce_string_list(entry.get("paths"))
        if _command_matches_scope(paths, scope_paths):
            return command.strip()
    for entry in command_index.values():
        if not isinstance(entry, dict):
            continue
        entry_kind = entry.get("kind")
        command = entry.get("command")
        if entry_kind != kind or not isinstance(command, str) or not command.strip():
            continue
        paths = _coerce_string_list(entry.get("paths"))
        if _command_matches_scope(paths, scope_paths):
            return command.strip()
    for key in preferred_keys:
        entry = command_index.get(key)
        command = entry.get("command") if isinstance(entry, dict) else None
        if isinstance(command, str) and command.strip():
            return command.strip()
    for entry in command_index.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") != kind:
            continue
        command = entry.get("command")
        if isinstance(command, str) and command.strip():
            return command.strip()
    return None


def _estimate_cost_cents(
    settings: Settings,
    tier: str | None,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    normalized_tier = str(tier or "tier_standard")
    pricing = {
        "tier_premium": (
            float(getattr(settings, "ai_tier_premium_input_cents_per_1k_tokens", 1.0)),
            float(getattr(settings, "ai_tier_premium_output_cents_per_1k_tokens", 4.0)),
        ),
        "tier_standard": (
            float(getattr(settings, "ai_tier_standard_input_cents_per_1k_tokens", 0.3)),
            float(getattr(settings, "ai_tier_standard_output_cents_per_1k_tokens", 1.2)),
        ),
        "tier_economy": (
            float(getattr(settings, "ai_tier_economy_input_cents_per_1k_tokens", 0.08)),
            float(getattr(settings, "ai_tier_economy_output_cents_per_1k_tokens", 0.3)),
        ),
        "tier_none": (0.0, 0.0),
    }
    in_rate, out_rate = pricing.get(normalized_tier, pricing["tier_standard"])
    return round((max(0, input_tokens) / 1000.0) * in_rate + (max(0, output_tokens) / 1000.0) * out_rate, 4)


def _edit_budget(summary: dict[str, Any] | None, settings: Settings | None = None) -> tuple[str, int, int]:
    cfg = settings or get_settings()
    budget = summary.get("edit_budget") if isinstance(summary, dict) else None
    scope_mode = "minimal_patch"
    file_budget = 5
    hard_file_budget = 15
    if isinstance(budget, dict):
        mode = budget.get("mode")
        if isinstance(mode, str) and mode.strip():
            scope_mode = mode.strip()
        max_files = budget.get("max_files")
        if isinstance(max_files, int) and max_files > 0:
            file_budget = max_files
        hard_max_files = budget.get("hard_max_files")
        if isinstance(hard_max_files, int) and hard_max_files > 0:
            hard_file_budget = hard_max_files
    file_budget = max(1, file_budget)
    hard_file_budget = max(file_budget, hard_file_budget)
    return scope_mode, file_budget, hard_file_budget


def _planned_run_cost_budget(plan_snapshot: dict[str, Any] | None, settings: Settings | None = None) -> float:
    cfg = settings or get_settings()
    default_budget = float(getattr(cfg, "codex_max_run_cost_cents", DEFAULT_CODEX_MAX_RUN_COST_CENTS))
    steps = plan_snapshot.get("steps") if isinstance(plan_snapshot, dict) else None
    if not isinstance(steps, list):
        return default_budget

    per_step_budget = float(getattr(cfg, "ai_budget_standard_cents", 8.0))
    planned_total = 0.0
    for step in steps:
        if not isinstance(step, dict):
            continue
        work_item_type = step.get("work_item_type")
        if not isinstance(work_item_type, str):
            continue
        if work_item_type.strip().upper() not in AI_BUDGETED_WORK_ITEM_TYPES:
            continue
        planned_total += per_step_budget

    return round(max(default_budget, planned_total), 4)


def _default_allowed_prefixes(settings: Settings | None = None) -> list[str]:
    cfg = settings or get_settings()
    raw = getattr(cfg, "workspace_allowed_command_prefixes", "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _coerce_state(
    value: Any,
    *,
    default: str,
    allowed: set[str],
    aliases: dict[str, str] | None = None,
) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return default
    if aliases and raw in aliases:
        raw = aliases[raw]
    return raw if raw in allowed else default


@dataclass
class ExecutionBudgetLedger:
    max_tokens: int
    max_cost_cents: float = DEFAULT_CODEX_MAX_RUN_COST_CENTS
    used_input_tokens: int = 0
    used_output_tokens: int = 0
    used_tokens: int = 0
    remaining_tokens: int = 0
    used_cost_cents: float = 0.0
    remaining_cost_cents: float = DEFAULT_CODEX_MAX_RUN_COST_CENTS
    recovery_reserve_cost_cents: float = 0.0
    used_recovery_cost_cents: float = 0.0
    remaining_recovery_cost_cents: float = 0.0
    active_budget_partition: str = "main"
    budget_mode: str = BudgetMode.NORMAL
    model_tier_cap: str | None = None
    completion_token_cap: int | None = None
    escalation_reason: str | None = None
    last_ai_job_id: str | None = None
    last_work_item_id: str | None = None
    last_model_tier: str | None = None
    updated_at: str | None = None

    def refresh(self, settings: Settings | None = None, *, recovery_mode: bool = False) -> None:
        cfg = settings or get_settings()
        codex_max_tokens = int(getattr(cfg, "codex_max_tokens", DEFAULT_CODEX_MAX_TOKENS))
        economy_completion_tokens = int(
            getattr(cfg, "ai_default_completion_economy_tokens", DEFAULT_ECONOMY_COMPLETION_TOKENS)
        )
        standard_completion_tokens = int(
            getattr(cfg, "ai_default_completion_standard_tokens", DEFAULT_STANDARD_COMPLETION_TOKENS)
        )
        background_budget_cents = float(getattr(cfg, "ai_budget_background_cents", 0.5))
        economy_budget_cents = float(getattr(cfg, "ai_budget_economy_cents", 2.0))
        self.max_tokens = max(0, int(self.max_tokens))
        self.max_cost_cents = max(0.0, float(self.max_cost_cents))
        configured_recovery_reserve = max(
            float(getattr(cfg, "ai_recovery_reserve_min_cents", 0.0)),
            self.max_cost_cents * max(0.0, float(getattr(cfg, "ai_recovery_reserve_fraction", 0.0))),
        )
        self.recovery_reserve_cost_cents = round(
            max(0.0, float(self.recovery_reserve_cost_cents or configured_recovery_reserve)),
            4,
        )
        self.used_input_tokens = max(0, int(self.used_input_tokens))
        self.used_output_tokens = max(0, int(self.used_output_tokens))
        self.used_tokens = max(0, int(self.used_input_tokens + self.used_output_tokens))
        self.remaining_tokens = max(0, int(self.max_tokens - self.used_tokens))
        self.used_cost_cents = round(max(0.0, float(self.used_cost_cents)), 4)
        self.used_recovery_cost_cents = round(max(0.0, float(self.used_recovery_cost_cents)), 4)
        self.remaining_recovery_cost_cents = round(
            max(0.0, self.recovery_reserve_cost_cents - self.used_recovery_cost_cents),
            4,
        )
        effective_max_cost_cents = self.max_cost_cents
        self.active_budget_partition = "main"
        fallback_to_main_budget = False
        if recovery_mode:
            recovery_remaining = round(max(0.0, self.recovery_reserve_cost_cents - self.used_recovery_cost_cents), 4)
            main_remaining = round(max(0.0, self.max_cost_cents - self.used_cost_cents), 4)
            if recovery_remaining <= background_budget_cents and main_remaining > background_budget_cents:
                # Recovery reserve is exhausted, but we still have main-run budget.
                # Fall back to main budget instead of hard-blocking recovery immediately.
                fallback_to_main_budget = True
                self.active_budget_partition = "main_fallback"
                effective_max_cost_cents = self.max_cost_cents
            else:
                effective_max_cost_cents = self.max_cost_cents + self.recovery_reserve_cost_cents
                self.active_budget_partition = "recovery"
        self.remaining_cost_cents = round(max(0.0, effective_max_cost_cents - self.used_cost_cents), 4)
        self.updated_at = _now_iso()

        recovery_reserve_exhausted = (
            recovery_mode
            and not fallback_to_main_budget
            and self.remaining_recovery_cost_cents <= background_budget_cents
        )
        if (
            self.remaining_tokens < max(256, economy_completion_tokens)
            or self.remaining_cost_cents <= background_budget_cents
            or recovery_reserve_exhausted
        ):
            self.budget_mode = BudgetMode.BLOCKED
            self.model_tier_cap = "tier_none"
            self.completion_token_cap = 0
            if recovery_reserve_exhausted:
                self.escalation_reason = "recovery_budget_exhausted"
            elif self.remaining_cost_cents <= background_budget_cents:
                self.escalation_reason = "run_cost_budget_exhausted"
            else:
                self.escalation_reason = "run_token_budget_exhausted"
            return

        if self.remaining_tokens < max(codex_max_tokens * 4, standard_completion_tokens * 2) or self.remaining_cost_cents <= economy_budget_cents:
            self.budget_mode = BudgetMode.CONSTRAINED
            self.model_tier_cap = "tier_economy"
            self.completion_token_cap = max(
                256,
                min(economy_completion_tokens, self.remaining_tokens // 2),
            )
            self.escalation_reason = (
                "run_cost_budget_low"
                if self.remaining_cost_cents <= economy_budget_cents
                else "run_token_budget_low"
            )
            return

        self.budget_mode = BudgetMode.NORMAL
        self.model_tier_cap = None
        self.completion_token_cap = min(codex_max_tokens, self.remaining_tokens)
        self.escalation_reason = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "max_cost_cents": self.max_cost_cents,
            "used_input_tokens": self.used_input_tokens,
            "used_output_tokens": self.used_output_tokens,
            "used_tokens": self.used_tokens,
            "remaining_tokens": self.remaining_tokens,
            "used_cost_cents": self.used_cost_cents,
            "remaining_cost_cents": self.remaining_cost_cents,
            "recovery_reserve_cost_cents": self.recovery_reserve_cost_cents,
            "used_recovery_cost_cents": self.used_recovery_cost_cents,
            "remaining_recovery_cost_cents": self.remaining_recovery_cost_cents,
            "active_budget_partition": self.active_budget_partition,
            "budget_mode": self.budget_mode,
            "model_tier_cap": self.model_tier_cap,
            "completion_token_cap": self.completion_token_cap,
            "escalation_reason": self.escalation_reason,
            "last_ai_job_id": self.last_ai_job_id,
            "last_work_item_id": self.last_work_item_id,
            "last_model_tier": self.last_model_tier,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None, settings: Settings | None = None) -> "ExecutionBudgetLedger":
        cfg = settings or get_settings()
        payload = value if isinstance(value, dict) else {}
        ledger = cls(
            max_tokens=int(payload.get("max_tokens") or getattr(cfg, "codex_max_run_tokens", DEFAULT_CODEX_MAX_RUN_TOKENS)),
            max_cost_cents=float(payload.get("max_cost_cents") or getattr(cfg, "codex_max_run_cost_cents", DEFAULT_CODEX_MAX_RUN_COST_CENTS)),
            used_input_tokens=int(payload.get("used_input_tokens") or 0),
            used_output_tokens=int(payload.get("used_output_tokens") or 0),
            used_cost_cents=float(payload.get("used_cost_cents") or 0.0),
            recovery_reserve_cost_cents=float(payload.get("recovery_reserve_cost_cents") or 0.0),
            used_recovery_cost_cents=float(payload.get("used_recovery_cost_cents") or 0.0),
            active_budget_partition=str(payload.get("active_budget_partition") or "main"),
            last_ai_job_id=payload.get("last_ai_job_id"),
            last_work_item_id=payload.get("last_work_item_id"),
            last_model_tier=payload.get("last_model_tier"),
        )
        ledger.refresh(cfg)
        return ledger


@dataclass
class ExecutionContract:
    version: int
    goal: str | None
    lifecycle_state: str
    scope_mode: str
    target_files: list[str]
    allowed_files: list[str]
    related_files: list[str]
    protected_paths: list[str]
    safe_paths: list[str]
    validation_steps: list[str]
    validation_recipes: list[str]
    success_criteria: list[str]
    command_index: dict[str, dict[str, Any]]
    build_command: str | None
    test_command: str | None
    lint_command: str | None
    allowed_command_prefixes: list[str]
    file_budget: int
    hard_file_budget: int
    risk_level: str
    assumptions_used: list[str]
    validation_state: str
    retry_state: str
    budget: ExecutionBudgetLedger

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal,
            "lifecycle_state": self.lifecycle_state,
            "scope_mode": self.scope_mode,
            "target_files": list(self.target_files),
            "allowed_files": list(self.allowed_files),
            "related_files": list(self.related_files),
            "protected_paths": list(self.protected_paths),
            "safe_paths": list(self.safe_paths),
            "validation_steps": list(self.validation_steps),
            "validation_recipes": list(self.validation_recipes),
            "success_criteria": list(self.success_criteria),
            "command_index": {key: dict(value) for key, value in self.command_index.items()},
            "build_command": self.build_command,
            "test_command": self.test_command,
            "lint_command": self.lint_command,
            "allowed_command_prefixes": list(self.allowed_command_prefixes),
            "file_budget": self.file_budget,
            "hard_file_budget": self.hard_file_budget,
            "risk_level": self.risk_level,
            "assumptions_used": list(self.assumptions_used),
            "validation_state": self.validation_state,
            "retry_state": self.retry_state,
            "budget": self.budget.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None, settings: Settings | None = None) -> "ExecutionContract" | None:
        if not isinstance(value, dict):
            return None
        cfg = settings or get_settings()
        return cls(
            version=int(value.get("version") or DEFAULT_CONTRACT_VERSION),
            goal=value.get("goal") if isinstance(value.get("goal"), str) else None,
            lifecycle_state=_coerce_state(
                value.get("lifecycle_state"),
                default=ContractLifecycleState.PENDING,
                allowed={state.value for state in ContractLifecycleState},
                aliases={
                    "QUEUED": ContractLifecycleState.PENDING,
                    "COMPLETED": ContractLifecycleState.SUCCESS,
                },
            ),
            scope_mode=str(value.get("scope_mode") or "minimal_patch"),
            target_files=_coerce_string_list(value.get("target_files")),
            allowed_files=_coerce_string_list(value.get("allowed_files")),
            related_files=_coerce_string_list(value.get("related_files")),
            protected_paths=_coerce_string_list(value.get("protected_paths")),
            safe_paths=_coerce_string_list(value.get("safe_paths")),
            validation_steps=_coerce_string_list(value.get("validation_steps")),
            validation_recipes=_coerce_string_list(value.get("validation_recipes")),
            success_criteria=_coerce_string_list(value.get("success_criteria")),
            command_index=_coerce_command_index(value.get("command_index")),
            build_command=value.get("build_command") if isinstance(value.get("build_command"), str) else None,
            test_command=value.get("test_command") if isinstance(value.get("test_command"), str) else None,
            lint_command=value.get("lint_command") if isinstance(value.get("lint_command"), str) else None,
            allowed_command_prefixes=_coerce_string_list(value.get("allowed_command_prefixes")),
            file_budget=max(1, int(value.get("file_budget") or 5)),
            hard_file_budget=max(
                int(value.get("file_budget") or 5),
                int(value.get("hard_file_budget") or 15),
            ),
            risk_level=str(value.get("risk_level") or "LOW").upper(),
            assumptions_used=_coerce_string_list(value.get("assumptions_used")),
            validation_state=_coerce_state(
                value.get("validation_state"),
                default=ValidationState.NOT_STARTED,
                allowed={state.value for state in ValidationState},
                aliases={
                    "QUEUED": ValidationState.PENDING,
                    "DONE": ValidationState.PASSED,
                    "COMPLETED": ValidationState.PASSED,
                },
            ),
            retry_state=_coerce_state(
                value.get("retry_state"),
                default=RetryState.IDLE,
                allowed={state.value for state in RetryState},
                aliases={
                    "SCHEDULED": RetryState.PENDING,
                    "DONE": RetryState.RECOVERED,
                },
            ),
            budget=ExecutionBudgetLedger.from_dict(value.get("budget"), cfg),
        )


def coerce_execution_contract(value: ExecutionContract | dict[str, Any] | None, settings: Settings | None = None) -> ExecutionContract | None:
    if isinstance(value, ExecutionContract):
        value.budget.refresh(settings)
        return value
    return ExecutionContract.from_dict(value, settings)


def build_execution_contract(
    *,
    run_summary: dict[str, Any] | None,
    architecture_profile: dict[str, Any] | None,
    plan_snapshot: dict[str, Any] | None,
    project_contract: dict[str, Any] | None = None,
    previous_contract: ExecutionContract | dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> ExecutionContract:
    cfg = settings or get_settings()
    summary = run_summary if isinstance(run_summary, dict) else {}
    architecture = architecture_profile if isinstance(architecture_profile, dict) else {}
    resolved_project_contract = (
        project_contract
        if isinstance(project_contract, dict)
        else summary.get("project_contract")
        if isinstance(summary.get("project_contract"), dict)
        else {}
    )
    plan = plan_snapshot if isinstance(plan_snapshot, dict) else {}
    previous = coerce_execution_contract(previous_contract, cfg)

    scope_mode, file_budget, hard_file_budget = _edit_budget(summary, cfg)
    target_files = _string_list_from_mapping(summary, "target_files")
    related_files = _string_list_from_mapping(summary, "expected_files", "files", "related_files")
    allowed_files = _unique_paths(target_files + related_files + _string_list_from_mapping(plan, "expected_files"))
    protected_paths = _coerce_string_list(architecture.get("protected_paths"))
    safe_paths = _coerce_string_list(architecture.get("safe_paths"))
    command_index = _coerce_command_index(architecture.get("command_index"))
    validation_recipe_index = architecture.get("validation_recipe_index")
    validation_recipes = (
        sorted(key for key in validation_recipe_index.keys() if isinstance(key, str))
        if isinstance(validation_recipe_index, dict)
        else []
    )
    validation_steps = _coerce_string_list(plan.get("validation_steps")) or validation_recipes
    success_criteria = _coerce_string_list(plan.get("success_criteria"))
    scope_paths = _unique_paths(target_files + allowed_files)
    build_command = _resolve_named_command(
        command_index,
        preferred_keys=["frontend_build", "backend_build", "root_build", "build"],
        kind="build",
        scope_paths=scope_paths,
    )
    test_command = _resolve_named_command(
        command_index,
        preferred_keys=["frontend_test", "static_frontend_test", "api_tests", "repo_tests", "backend_test", "test"],
        kind="test",
        scope_paths=scope_paths,
    ) or getattr(cfg, "test_command", "pytest -q")
    lint_command = _resolve_named_command(
        command_index,
        preferred_keys=["frontend_lint", "backend_lint", "repo_lint", "lint"],
        kind="lint",
        scope_paths=scope_paths,
    )

    architecture_summary = architecture.get("summary")
    assumptions_used = []
    if isinstance(architecture_summary, dict):
        assumptions_used = _coerce_string_list(architecture_summary.get("assumptions_used"))
    if isinstance(resolved_project_contract, dict):
        project_assumptions = _coerce_string_list(resolved_project_contract.get("assumptions_used"))
        assumptions_used = _unique_paths(assumptions_used + project_assumptions)

    allowed_command_prefixes = _unique_paths(
        _default_allowed_prefixes(cfg)
        + _prefixes_from_commands(command_index)
        + _prefixes_from_commands(
            {
                "build": {"command": build_command} if build_command else {},
                "test": {"command": test_command} if test_command else {},
                "lint": {"command": lint_command} if lint_command else {},
            }
        )
    )
    planned_run_cost_budget = _planned_run_cost_budget(plan, cfg)
    if previous is not None:
        previous.budget.max_cost_cents = max(float(previous.budget.max_cost_cents), planned_run_cost_budget)
        budget = previous.budget
    else:
        budget = ExecutionBudgetLedger(
            max_tokens=int(getattr(cfg, "codex_max_run_tokens", DEFAULT_CODEX_MAX_RUN_TOKENS)),
            max_cost_cents=planned_run_cost_budget,
        )
    budget.refresh(cfg)

    validation_state = previous.validation_state if previous is not None else (ValidationState.PENDING if validation_steps else ValidationState.NOT_REQUIRED)
    retry_state = previous.retry_state if previous is not None else RetryState.IDLE
    lifecycle_state = previous.lifecycle_state if previous is not None else ContractLifecycleState.PENDING

    goal = summary.get("goal") or plan.get("goal")
    return ExecutionContract(
        version=DEFAULT_CONTRACT_VERSION,
        goal=goal.strip() if isinstance(goal, str) and goal.strip() else None,
        lifecycle_state=str(lifecycle_state),
        scope_mode=scope_mode,
        target_files=target_files,
        allowed_files=allowed_files,
        related_files=related_files,
        protected_paths=protected_paths,
        safe_paths=safe_paths,
        validation_steps=validation_steps,
        validation_recipes=validation_recipes,
        success_criteria=success_criteria,
        command_index=command_index,
        build_command=build_command,
        test_command=test_command,
        lint_command=lint_command,
        allowed_command_prefixes=allowed_command_prefixes,
        file_budget=file_budget,
        hard_file_budget=hard_file_budget,
        risk_level=str(plan.get("risk_level") or "LOW").upper(),
        assumptions_used=assumptions_used,
        validation_state=validation_state,
        retry_state=retry_state,
        budget=budget,
    )


def update_summary_execution_contract(
    summary: dict[str, Any] | None,
    *,
    architecture_profile: dict[str, Any] | None = None,
    project_contract: dict[str, Any] | None = None,
    plan_snapshot: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    payload = dict(summary or {})
    contract = build_execution_contract(
        run_summary=payload,
        architecture_profile=architecture_profile,
        project_contract=project_contract
        or (payload.get("project_contract") if isinstance(payload.get("project_contract"), dict) else None),
        plan_snapshot=plan_snapshot or (payload.get("plan_snapshot") if isinstance(payload.get("plan_snapshot"), dict) else None),
        previous_contract=payload.get("execution_contract"),
        settings=settings,
    )
    payload["execution_contract"] = contract.to_dict()
    return payload


def _derive_validation_state(run: Run, work_items: list[WorkItem]) -> str:
    if run.workspace_status == "ERROR":
        return ValidationState.BLOCKED
    validation_items = [item for item in work_items if item.type in VALIDATION_WORK_ITEM_TYPES]
    effective_validation_items = [item for item in validation_items if not is_superseded_failure(item)]
    if not effective_validation_items:
        return ValidationState.NOT_STARTED
    if any(is_blocking_failure(item) for item in effective_validation_items):
        return ValidationState.FAILED
    if any(item.status in {"RUNNING", "CLAIMED"} for item in effective_validation_items):
        return ValidationState.RUNNING
    if any(item.status == "QUEUED" for item in effective_validation_items):
        return ValidationState.PENDING
    if any(is_non_blocking_failure(item) for item in effective_validation_items):
        return ValidationState.PASSED_WITH_WARNINGS
    if all(item.status in {"DONE", "SKIPPED"} for item in effective_validation_items):
        return ValidationState.PASSED
    return ValidationState.IN_PROGRESS


def _is_recovery_work_item(item: WorkItem) -> bool:
    payload = item.payload if isinstance(item.payload, dict) else {}
    result = item.result if isinstance(item.result, dict) else {}
    return any(
        payload.get(key) for key in ("recovery_action", "recovery_source_id", "failed_work_item_id")
    ) or any(
        result.get(key) for key in ("recovery_action", "retry_state")
    )


def is_recovery_work_item(item: WorkItem) -> bool:
    return _is_recovery_work_item(item)


def _derive_retry_state(work_items: list[WorkItem]) -> str:
    if any(
        _is_recovery_work_item(item)
        and item.status == "FAILED"
        and isinstance(item.result, dict)
        and item.result.get("message") == "run_budget_exhausted"
        for item in work_items
    ):
        return RetryState.BLOCKED_BUDGET
    if any(
        _is_recovery_work_item(item) and item.status in {"QUEUED", "RUNNING", "CLAIMED"}
        for item in work_items
    ):
        return RetryState.RETRYING
    if any(
        isinstance(item.result, dict) and str(item.result.get("retry_state") or "").upper() == "EXHAUSTED"
        for item in work_items
    ):
        return RetryState.EXHAUSTED
    if any(_is_recovery_work_item(item) and item.status in {"DONE", "SKIPPED"} for item in work_items):
        return RetryState.RECOVERED
    if any(_is_recovery_work_item(item) for item in work_items):
        return RetryState.PENDING
    return RetryState.IDLE


def _derive_lifecycle_state(run: Run, work_items: list[WorkItem], *, validation_state: str, retry_state: str) -> str:
    if run.workspace_status == "ERROR":
        return ContractLifecycleState.BLOCKED
    if retry_state == RetryState.RETRYING:
        return ContractLifecycleState.RETRYING
    if run.status == "FAILED" or validation_state == ValidationState.FAILED:
        return ContractLifecycleState.FAILED
    if validation_state in {ValidationState.PENDING, ValidationState.RUNNING, ValidationState.IN_PROGRESS}:
        return ContractLifecycleState.VALIDATING
    if run.status == "COMPLETED" and validation_state in {
        ValidationState.PASSED,
        ValidationState.PASSED_WITH_WARNINGS,
        ValidationState.NOT_REQUIRED,
        ValidationState.NOT_STARTED,
    }:
        return ContractLifecycleState.SUCCESS
    if any(item.status in {"RUNNING", "CLAIMED"} for item in work_items):
        return ContractLifecycleState.RUNNING
    if any(item.status == "QUEUED" for item in work_items) or run.status == "QUEUED":
        return ContractLifecycleState.PENDING
    return ContractLifecycleState.RUNNING


async def sync_run_execution_contract_state(session: AsyncSession, run: Run) -> ExecutionContract:
    summary = dict(run.summary or {})
    contract = build_execution_contract(
        run_summary=summary,
        architecture_profile=(summary.get("architecture_profile") if isinstance(summary.get("architecture_profile"), dict) else None),
        project_contract=(summary.get("project_contract") if isinstance(summary.get("project_contract"), dict) else None),
        plan_snapshot=(summary.get("plan_snapshot") if isinstance(summary.get("plan_snapshot"), dict) else None),
        previous_contract=summary.get("execution_contract"),
    )
    work_items = (
        await session.execute(
            select(WorkItem).where(WorkItem.run_id == run.id).order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
        )
    ).scalars().all()
    contract.validation_state = _derive_validation_state(run, work_items)
    contract.retry_state = _derive_retry_state(work_items)
    contract.lifecycle_state = _derive_lifecycle_state(
        run,
        work_items,
        validation_state=contract.validation_state,
        retry_state=contract.retry_state,
    )
    summary["execution_contract"] = contract.to_dict()
    run.summary = summary
    session.add(run)
    await session.flush()
    return contract


async def record_run_budget_usage(
    session: AsyncSession,
    run: Run,
    *,
    work_item_id: str | None,
    ai_job_id: str | None,
    selected_model_tier: str | None,
    input_tokens: int,
    output_tokens: int,
) -> ExecutionContract:
    work_item: WorkItem | None = None
    if work_item_id:
        try:
            work_item = await session.get(WorkItem, uuid.UUID(str(work_item_id)))
        except Exception:
            work_item = None
    recovery_mode = bool(work_item is not None and _is_recovery_work_item(work_item))
    summary = dict(run.summary or {})
    contract = build_execution_contract(
        run_summary=summary,
        architecture_profile=(summary.get("architecture_profile") if isinstance(summary.get("architecture_profile"), dict) else None),
        project_contract=(summary.get("project_contract") if isinstance(summary.get("project_contract"), dict) else None),
        plan_snapshot=(summary.get("plan_snapshot") if isinstance(summary.get("plan_snapshot"), dict) else None),
        previous_contract=summary.get("execution_contract"),
    )
    contract.budget.used_input_tokens += max(0, int(input_tokens))
    contract.budget.used_output_tokens += max(0, int(output_tokens))
    estimated_cost_cents = _estimate_cost_cents(
        get_settings(),
        selected_model_tier,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    contract.budget.used_cost_cents += estimated_cost_cents
    if recovery_mode:
        contract.budget.used_recovery_cost_cents += estimated_cost_cents
    contract.budget.last_work_item_id = work_item_id
    contract.budget.last_ai_job_id = ai_job_id
    contract.budget.last_model_tier = selected_model_tier
    contract.budget.refresh(recovery_mode=recovery_mode)
    summary["execution_contract"] = contract.to_dict()
    run.summary = summary
    session.add(run)
    await session.flush()
    return contract
