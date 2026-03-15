import uuid

import pytest
from pydantic import ValidationError

from app.db.models import Task
from app.schemas.persistence import TaskCreate
from app.services.task_branching import resolve_task_branch_plan


def _make_task(*, strategy: str, branch_name: str | None = None, base_branch: str | None = None) -> Task:
    return Task(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="GitHub pipeline smoke test",
        branch_strategy=strategy,
        branch_name=branch_name,
        base_branch=base_branch,
    )


def test_task_create_auto_strategy_clears_manual_branch_values():
    payload = TaskCreate(
        title="Smoke test",
        branch_strategy="AUTO",
        branch_name="feature/ignored",
        base_branch="main",
    )

    assert payload.branch_strategy == "auto"
    assert payload.branch_name is None
    assert payload.base_branch is None


@pytest.mark.parametrize("strategy", ["new", "existing"])
def test_task_create_requires_branch_name_for_non_auto_strategies(strategy: str):
    with pytest.raises(ValidationError):
        TaskCreate(title="Smoke test", branch_strategy=strategy)


def test_resolve_new_branch_plan_uses_requested_base_branch():
    task = _make_task(
        strategy="new",
        branch_name="feature/login-form",
        base_branch="release/2026.03",
    )

    plan = resolve_task_branch_plan(task, "main")

    assert plan.strategy == "new"
    assert plan.requested_branch_name == "feature/login-form"
    assert plan.actual_branch_name == "feature/login-form"
    assert plan.base_branch == "release/2026.03"


def test_resolve_existing_branch_plan_reuses_branch_as_base():
    task = _make_task(strategy="existing", branch_name="feature/auth-refactor")

    plan = resolve_task_branch_plan(task, "main")

    assert plan.strategy == "existing"
    assert plan.requested_branch_name == "feature/auth-refactor"
    assert plan.actual_branch_name == "feature/auth-refactor"
    assert plan.base_branch == "feature/auth-refactor"


def test_resolve_auto_branch_plan_falls_back_to_project_default_branch():
    task = _make_task(strategy="auto", branch_name="feature/ignored", base_branch="release/ignored")

    plan = resolve_task_branch_plan(task, "develop")

    assert plan.strategy == "auto"
    assert plan.requested_branch_name is None
    assert plan.actual_branch_name is None
    assert plan.base_branch == "develop"
