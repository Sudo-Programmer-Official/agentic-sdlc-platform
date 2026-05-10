from __future__ import annotations

from typing import Any


def work_item_payload(item: Any) -> dict[str, Any]:
    payload = getattr(item, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _work_item_result(item: Any) -> dict[str, Any]:
    result = getattr(item, "result", None)
    return result if isinstance(result, dict) else {}


def _is_budget_related_failure(item: Any) -> bool:
    if getattr(item, "status", None) != "FAILED":
        return False
    result = _work_item_result(item)
    failure_class = str(result.get("failure_class") or "").lower()
    stop_reason = str(result.get("stop_reason") or "").lower()
    last_error = str(getattr(item, "last_error", "") or "").lower()
    return (
        "budget_exceeded" in failure_class
        or "budget_exhausted" in failure_class
        or "budget_exceeded" in stop_reason
        or "budget_exhausted" in stop_reason
        or "budget_exceeded" in last_error
        or "budget_exhausted" in last_error
    )


def is_superseded_failure(item: Any) -> bool:
    result = _work_item_result(item)
    return getattr(item, "status", None) == "FAILED" and isinstance(result, dict) and result.get("superseded") is True


def is_non_blocking_failure(item: Any) -> bool:
    if _is_budget_related_failure(item):
        return True
    payload = work_item_payload(item)
    # WRITE_TESTS is soft-fail by default so downstream review/validation can continue.
    if getattr(item, "type", None) == "WRITE_TESTS" and payload.get("blocking", False) is not True:
        return getattr(item, "status", None) == "FAILED" and not is_superseded_failure(item)
    return (
        getattr(item, "status", None) == "FAILED"
        and not is_superseded_failure(item)
        and payload.get("blocking", True) is False
    )


def is_blocking_failure(item: Any) -> bool:
    return (
        getattr(item, "status", None) == "FAILED"
        and not is_superseded_failure(item)
        and not is_non_blocking_failure(item)
    )


def is_optional_work_item(item: Any) -> bool:
    return work_item_payload(item).get("blocking", True) is False


def is_dependency_satisfied(item: Any) -> bool:
    status = getattr(item, "status", None)
    if status in {"DONE", "SKIPPED"}:
        return True
    if status == "FAILED":
        return not is_blocking_failure(item)
    return False
