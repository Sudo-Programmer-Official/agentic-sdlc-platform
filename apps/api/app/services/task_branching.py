from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from app.db.models.task import Task

TaskBranchStrategy = Literal["auto", "new", "existing"]
VALID_TASK_BRANCH_STRATEGIES: tuple[TaskBranchStrategy, ...] = ("auto", "new", "existing")


@dataclass(frozen=True)
class TaskBranchPlan:
    strategy: TaskBranchStrategy
    requested_branch_name: str | None
    actual_branch_name: str | None
    base_branch: str | None


def clean_branch_value(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def normalize_task_branch_strategy(value: str | None) -> TaskBranchStrategy:
    normalized = (value or "auto").strip().lower()
    if normalized not in VALID_TASK_BRANCH_STRATEGIES:
        return "auto"
    return cast(TaskBranchStrategy, normalized)


def resolve_task_branch_plan(task: Task | None, default_branch: str | None) -> TaskBranchPlan:
    normalized_default_branch = clean_branch_value(default_branch) or "main"
    if task is None:
        return TaskBranchPlan(
            strategy="auto",
            requested_branch_name=None,
            actual_branch_name=None,
            base_branch=normalized_default_branch,
        )

    strategy = normalize_task_branch_strategy(getattr(task, "branch_strategy", None))
    requested_branch_name = clean_branch_value(getattr(task, "branch_name", None))
    requested_base_branch = clean_branch_value(getattr(task, "base_branch", None))

    if strategy == "new":
        if not requested_branch_name:
            raise ValueError("Task branch strategy 'new' requires a branch name.")
        return TaskBranchPlan(
            strategy="new",
            requested_branch_name=requested_branch_name,
            actual_branch_name=requested_branch_name,
            base_branch=requested_base_branch or normalized_default_branch,
        )

    if strategy == "existing":
        if not requested_branch_name:
            raise ValueError("Task branch strategy 'existing' requires a branch name.")
        return TaskBranchPlan(
            strategy="existing",
            requested_branch_name=requested_branch_name,
            actual_branch_name=requested_branch_name,
            base_branch=requested_branch_name,
        )

    return TaskBranchPlan(
        strategy="auto",
        requested_branch_name=None,
        actual_branch_name=None,
        base_branch=normalized_default_branch,
    )
