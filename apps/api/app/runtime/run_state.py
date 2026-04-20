from __future__ import annotations

from enum import StrEnum


class ContractLifecycleState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"


class ValidationState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    PASSED = "PASSED"
    PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"


class RetryState(StrEnum):
    IDLE = "IDLE"
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    RECOVERED = "RECOVERED"
    EXHAUSTED = "EXHAUSTED"
    BLOCKED = "BLOCKED"


class BudgetMode(StrEnum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"
    BLOCKED = "BLOCKED"
