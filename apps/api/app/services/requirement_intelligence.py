from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def derive_requirement_intelligence(
    *,
    requirement_updated_at: datetime | None,
    tasks: list[Any],
    runs: list[Any],
    improvements: list[Any],
    related_files: list[str],
    related_modules: list[str],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    failed_tasks = [task for task in tasks if str(getattr(task, "status", "")).upper() in {"FAILED", "CANCELED", "BLOCKED"}]
    failed_runs = [run for run in runs if str(getattr(run, "status", "")).upper() in {"FAILED", "CANCELED"}]
    retry_count = sum(1 for task in tasks if isinstance(getattr(task, "provenance", None), dict) and task.provenance.get("rerun_of_task_id"))
    unresolved_improvements = [
        item
        for item in improvements
        if str(getattr(item, "resolution_status", "") or getattr(item, "status", "")).upper()
        not in {"RESOLVED", "COMPLETED", "DONE"}
    ]

    recent_runs = sorted(
        runs,
        key=lambda run: _as_utc(getattr(run, "updated_at", None) or getattr(run, "finished_at", None) or getattr(run, "created_at", None))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    latest_run_at = _as_utc(
        (getattr(recent_runs[0], "updated_at", None) or getattr(recent_runs[0], "finished_at", None) or getattr(recent_runs[0], "created_at", None))
        if recent_runs
        else None
    )
    stale = bool(requirement_updated_at and (latest_run_at is None or now - latest_run_at > timedelta(days=14)))

    recurring_failures: list[str] = []
    error_counter: Counter[str] = Counter()
    for task in failed_tasks:
        err = (getattr(task, "last_error", None) or "").strip()
        if err:
            error_counter[err[:120]] += 1
    for run in failed_runs:
        summary = getattr(run, "summary", None)
        if isinstance(summary, dict):
            err = str(summary.get("primary_error") or summary.get("strategy_error") or "").strip()
            if err:
                error_counter[err[:120]] += 1
    recurring_failures = [msg for msg, count in error_counter.most_common(5) if count >= 2]

    file_counter: Counter[str] = Counter(path for path in related_files if path)
    module_counter: Counter[str] = Counter(module for module in related_modules if module)
    impacted_modules = [module for module, _ in module_counter.most_common(5)]
    frequent_files = [path for path, _ in file_counter.most_common(5)]

    recurring_validation_failures = sum(
        1
        for msg in error_counter
        if any(token in msg.lower() for token in ("test", "pytest", "assert", "validation", "lint"))
    )

    patch_violations = 0
    for run in runs:
        summary = getattr(run, "summary", None)
        if isinstance(summary, dict):
            records = summary.get("project_contract_violations")
            if isinstance(records, list):
                patch_violations += len(records)

    health = 100
    health -= len(failed_tasks) * 10
    health -= len(failed_runs) * 15
    health -= len(unresolved_improvements) * 10
    if stale:
        health -= 5
    health -= recurring_validation_failures * 5
    health -= min(patch_violations, 4) * 5
    health = max(0, min(100, health))
    risk = "LOW" if health >= 75 else "MEDIUM" if health >= 50 else "HIGH"

    stability_score = max(0, min(100, 100 - (len(failed_runs) * 10 + retry_count * 5)))
    unstable = retry_count >= 2 or len(recurring_failures) > 0

    return {
        "health_score": health,
        "risk_level": risk,
        "stability_score": stability_score,
        "retry_count": retry_count,
        "unresolved_count": len(unresolved_improvements),
        "recurring_failure_patterns": recurring_failures,
        "most_impacted_modules": impacted_modules,
        "frequently_modified_files": frequent_files,
        "stale": stale,
        "unstable": unstable,
    }
