from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, WorkItem
from app.services.work_item_state import is_blocking_failure, is_non_blocking_failure, is_superseded_failure

MAX_SUBTASKS = 5
MAX_FILES_PER_TASK = 5
MAX_DEPENDENCY_DEPTH = 2


@dataclass(frozen=True)
class DecompositionBucket:
    key: str
    title: str
    description: str
    work_item_types: tuple[str, ...]


@dataclass(frozen=True)
class DecompositionTemplate:
    key: str
    label: str
    description: str
    buckets: tuple[DecompositionBucket, ...]


TEMPLATES: tuple[DecompositionTemplate, ...] = (
    DecompositionTemplate(
        key="test_fix",
        label="Test Fix",
        description="Resolve a failing or missing test path with the smallest bounded patch possible.",
        buckets=(
            DecompositionBucket("isolate_failure", "Isolate failure", "Confirm the failing validation path and locate the smallest fix surface.", ("PLAN_DAG",)),
            DecompositionBucket("patch_test_or_code", "Patch code or tests", "Apply the minimal code or test change needed to resolve the failure.", ("CODE_BACKEND", "CODE_FRONTEND", "WRITE_TESTS")),
            DecompositionBucket("rerun_tests", "Rerun tests", "Re-run the affected validation path to confirm the fix holds.", ("RUN_TESTS",)),
            DecompositionBucket("review_delivery", "Review delivery", "Review the patch and integration handoff before delivery.", ("REVIEW_DIFF", "REVIEW_INTEGRATION")),
        ),
    ),
    DecompositionTemplate(
        key="api_feature",
        label="API Feature",
        description="Add or extend a bounded API capability without expanding into a broad refactor.",
        buckets=(
            DecompositionBucket("design_api_surface", "Design API surface", "Bound the endpoint or service contract before code generation starts.", ("PLAN_DAG",)),
            DecompositionBucket("implement_backend_api", "Implement backend API", "Apply backend changes for the new or updated API path.", ("CODE_BACKEND",)),
            DecompositionBucket("integrate_client", "Integrate client", "Update the consuming client or UI path if the feature crosses the API boundary.", ("CODE_FRONTEND",)),
            DecompositionBucket("validate_api", "Validate API", "Update tests and rerun validation against the scoped API flow.", ("WRITE_TESTS", "RUN_TESTS")),
            DecompositionBucket("review_delivery", "Review delivery", "Review the patch and integration handoff before delivery.", ("REVIEW_DIFF", "REVIEW_INTEGRATION")),
        ),
    ),
    DecompositionTemplate(
        key="small_ui_change",
        label="Small UI Change",
        description="Apply a focused UI or copy change while keeping the patch inside the frontend surface.",
        buckets=(
            DecompositionBucket("inspect_ui_scope", "Inspect UI scope", "Locate the targeted UI surface and bound the change before editing.", ("PLAN_DAG",)),
            DecompositionBucket("update_ui", "Update UI implementation", "Apply the minimal UI patch needed to satisfy the goal.", ("CODE_FRONTEND", "CODE_BACKEND")),
            DecompositionBucket("validate_ui", "Validate UI", "Update relevant tests and rerun validation for the changed UI surface.", ("WRITE_TESTS", "RUN_TESTS")),
            DecompositionBucket("review_delivery", "Review delivery", "Review the patch and integration handoff before delivery.", ("REVIEW_DIFF", "REVIEW_INTEGRATION")),
        ),
    ),
    DecompositionTemplate(
        key="bug_fix",
        label="Bug Fix",
        description="Patch a bounded defect, validate it, and keep the resulting patch reviewable.",
        buckets=(
            DecompositionBucket("analyze_issue", "Analyze issue", "Confirm the failing behavior and identify the bounded fix surface.", ("PLAN_DAG",)),
            DecompositionBucket("patch_fix", "Patch affected modules", "Apply the smallest backend or frontend patch that resolves the defect.", ("CODE_BACKEND", "CODE_FRONTEND")),
            DecompositionBucket("validate_fix", "Validate fix", "Update tests if needed and rerun validation before review.", ("WRITE_TESTS", "RUN_TESTS")),
            DecompositionBucket("review_delivery", "Review delivery", "Review the patch and integration handoff before delivery.", ("REVIEW_DIFF", "REVIEW_INTEGRATION")),
        ),
    ),
    DecompositionTemplate(
        key="bounded_change",
        label="Bounded Change",
        description="Move the requested change through a small, reviewable execution envelope.",
        buckets=(
            DecompositionBucket("analyze_request", "Analyze request", "Bound the requested change before any patching begins.", ("PLAN_DAG",)),
            DecompositionBucket("apply_patch", "Apply patch", "Apply the smallest patch required to move the goal forward.", ("CODE_BACKEND", "CODE_FRONTEND")),
            DecompositionBucket("validate_change", "Validate change", "Update tests if needed and rerun validation before review.", ("WRITE_TESTS", "RUN_TESTS")),
            DecompositionBucket("review_delivery", "Review delivery", "Review the patch and integration handoff before delivery.", ("REVIEW_DIFF", "REVIEW_INTEGRATION")),
        ),
    ),
)


def _goal_for_run(run: Run) -> str | None:
    if isinstance(run.summary, dict):
        goal = run.summary.get("goal") or run.summary.get("strategy_goal")
        if isinstance(goal, str) and goal.strip():
            return goal.strip()
    return None


def _choose_template(goal: str | None) -> DecompositionTemplate:
    text = (goal or "").lower()
    if any(token in text for token in ("test", "tests", "fixture", "spec", "failing")):
        return TEMPLATES[0]
    if any(token in text for token in ("api", "endpoint", "route", "csv", "export", "webhook", "backend")):
        return TEMPLATES[1]
    if any(token in text for token in ("ui", "button", "copy", "css", "style", "layout", "text", "page", "view", "component")):
        return TEMPLATES[2]
    if any(token in text for token in ("bug", "fix", "issue", "error", "failure", "timezone", "cors")):
        return TEMPLATES[3]
    return TEMPLATES[4]

def _aggregate_status(items: list[WorkItem]) -> str:
    effective_items = [item for item in items if not is_superseded_failure(item)] or items
    statuses = {item.status for item in effective_items}
    if any(is_blocking_failure(item) for item in effective_items):
        return "FAILED"
    if any(is_non_blocking_failure(item) for item in effective_items):
        residual_statuses = {item.status for item in effective_items if not is_non_blocking_failure(item)}
        if not residual_statuses or residual_statuses.issubset({"DONE", "SKIPPED"}):
            return "WARNING"
    if "CANCELED" in statuses:
        return "CANCELED"
    if "RUNNING" in statuses or "CLAIMED" in statuses:
        return "RUNNING"
    if statuses == {"SKIPPED"}:
        return "SKIPPED"
    if statuses and statuses.issubset({"DONE", "SKIPPED"}):
        return "DONE"
    if "QUEUED" in statuses:
        return "QUEUED"
    return next(iter(statuses), "QUEUED")


def _expected_files_for(items: list[WorkItem]) -> list[str]:
    files: list[str] = []
    for item in items:
        payload = item.payload or {}
        value = payload.get("expected_files") or payload.get("files")
        if isinstance(value, list):
            files.extend(str(path) for path in value if isinstance(path, str) and path.strip())
    return list(dict.fromkeys(files))[:MAX_FILES_PER_TASK]


def _risk_level(template_key: str, subtask_count: int) -> str:
    if subtask_count > MAX_SUBTASKS:
        return "HIGH"
    if template_key in {"api_feature", "bug_fix"}:
        return "MEDIUM"
    return "LOW"


def build_task_decomposition(run: Run, work_items: list[WorkItem]) -> dict:
    goal = _goal_for_run(run)
    template = _choose_template(goal)
    subtasks: list[dict] = []
    prior_ids: list[str] = []

    for bucket in template.buckets:
        bucket_items = [item for item in work_items if item.type in bucket.work_item_types]
        if not bucket_items:
            continue
        subtask_id = f"{template.key}:{bucket.key}"
        subtasks.append(
            {
                "id": subtask_id,
                "title": bucket.title,
                "description": bucket.description,
                "status": _aggregate_status(bucket_items),
                "blocking": not any(is_non_blocking_failure(item) for item in bucket_items if not is_superseded_failure(item)),
                "depends_on": prior_ids[-1:] if prior_ids else [],
                "work_item_ids": [str(item.id) for item in bucket_items],
                "work_item_types": list(dict.fromkeys(item.type for item in bucket_items)),
                "expected_files": _expected_files_for(bucket_items),
                "retry_scope": "subtask",
                "max_files": MAX_FILES_PER_TASK,
            }
        )
        prior_ids.append(subtask_id)

    requires_confirmation = len(subtasks) > MAX_SUBTASKS
    return {
        "goal": goal,
        "template_key": template.key,
        "template_label": template.label,
        "description": template.description,
        "risk_level": _risk_level(template.key, len(subtasks)),
        "requires_confirmation": requires_confirmation,
        "max_subtasks": MAX_SUBTASKS,
        "max_files_per_task": MAX_FILES_PER_TASK,
        "max_dependency_depth": MAX_DEPENDENCY_DEPTH,
        "subtasks": subtasks,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "runtime_template",
    }


async def persist_run_task_decomposition(session: AsyncSession, run: Run) -> dict:
    work_items = (
        await session.execute(
            select(WorkItem)
            .where(WorkItem.run_id == run.id)
            .order_by(WorkItem.priority.desc(), WorkItem.created_at.asc())
        )
    ).scalars().all()
    decomposition = build_task_decomposition(run, work_items)
    summary = dict(run.summary or {})
    summary["task_decomposition"] = decomposition
    run.summary = summary
    session.add(run)
    await session.flush()

    if run.workspace_root:
        context_dir = Path(run.workspace_root) / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        (context_dir / "task_decomposition.json").write_text(
            json.dumps(decomposition, indent=2) + "\n",
            encoding="utf-8",
        )

    return decomposition
