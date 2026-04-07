from __future__ import annotations

from typing import Any


def work_item_payload(item: Any) -> dict[str, Any]:
    payload = getattr(item, "payload", None)
    return payload if isinstance(payload, dict) else {}


def is_superseded_failure(item: Any) -> bool:
    result = getattr(item, "result", None)
    return getattr(item, "status", None) == "FAILED" and isinstance(result, dict) and result.get("superseded") is True


def is_non_blocking_failure(item: Any) -> bool:
    return (
        getattr(item, "status", None) == "FAILED"
        and not is_superseded_failure(item)
        and work_item_payload(item).get("blocking", True) is False
    )


def is_blocking_failure(item: Any) -> bool:
    return (
        getattr(item, "status", None) == "FAILED"
        and not is_superseded_failure(item)
        and not is_non_blocking_failure(item)
    )


def is_optional_work_item(item: Any) -> bool:
    return work_item_payload(item).get("blocking", True) is False
