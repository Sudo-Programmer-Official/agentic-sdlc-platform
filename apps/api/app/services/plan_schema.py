from __future__ import annotations

from typing import List, Optional, Set

from pydantic import BaseModel, Field, model_validator
from pydantic import ConfigDict


class PlanTask(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str
    title: str
    agent: str
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    parallel_group: str = "A"
    est_effort: Optional[str] = None
    linked_requirements: List[str] = Field(default_factory=list)


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    plan_id: str
    project_id: str
    stage: str
    plan_version: int | None = None
    parent_plan_id: str | None = None
    regeneration_mode: str | None = None
    changed_requirements: List[str] = Field(default_factory=list)
    reused_task_ids: List[str] = Field(default_factory=list)
    regenerated_task_ids: List[str] = Field(default_factory=list)
    max_parallel_tasks: int = 2
    requirements_sha: str | None = None
    created_at: str | None = None
    tasks: List[PlanTask]

    @model_validator(mode="after")
    def _validate_plan(self) -> "Plan":
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if len(self.tasks) > 12:
            raise ValueError("max_tasks_per_plan exceeded (12)")

        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id values must be unique")

        task_map = {task.task_id: task for task in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in task_map:
                    raise ValueError(f"Task {task.task_id} depends on unknown task {dep}")

        if _has_cycle(task_map):
            raise ValueError("Plan dependencies contain a cycle")
        return self


def _has_cycle(task_map: dict[str, PlanTask]) -> bool:
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        for dep in task_map[task_id].depends_on:
            if visit(dep):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    return any(visit(task_id) for task_id in task_map)
