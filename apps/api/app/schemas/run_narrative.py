from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.persistence import RunOut
from app.schemas.run_timeline import RunTimelineSummary


class RunPlanStep(BaseModel):
    id: str
    title: str
    phase: str
    status: str
    rationale: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    expected_commands: list[str] = Field(default_factory=list)
    work_item_id: uuid.UUID | None = None
    work_item_type: str | None = None
    executor: str | None = None


class RunPlanSnapshot(BaseModel):
    goal: str | None = None
    rationale: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    expected_commands: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    risk_level: str = "LOW"
    confidence_score: float | None = None
    steps: list[RunPlanStep] = Field(default_factory=list)


class RunPatchPlan(BaseModel):
    goal: str | None = None
    subsystem: str | None = None
    primary_files: list[str] = Field(default_factory=list)
    dependent_files: list[str] = Field(default_factory=list)
    related_tests: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    risk_level: str = "LOW"
    scope_depth: int = 1
    total_scope_files: int = 0


class RunPatchVerificationFinding(BaseModel):
    code: str
    severity: str
    title: str
    detail: str
    files: list[str] = Field(default_factory=list)


class RunPatchVerificationSummary(BaseModel):
    status: str = "READY"
    requires_confirmation: bool = False
    risk_level: str = "LOW"
    confidence_score: float | None = None
    subsystem: str | None = None
    file_count: int = 0
    scope_depth: int = 1
    max_files: int = 5
    max_dependency_depth: int = 2
    nearest_tests: list[str] = Field(default_factory=list)
    verified_files: list[str] = Field(default_factory=list)
    findings: list[RunPatchVerificationFinding] = Field(default_factory=list)
    suggested_next_action: str | None = None


class RunExecutionSubtask(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    depends_on: list[str] = Field(default_factory=list)
    work_item_ids: list[str] = Field(default_factory=list)
    work_item_types: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    retry_scope: str = "subtask"
    max_files: int = 5


class RunTaskDecomposition(BaseModel):
    goal: str | None = None
    template_key: str = "bounded_change"
    template_label: str = "Bounded Change"
    description: str | None = None
    risk_level: str = "LOW"
    requires_confirmation: bool = False
    max_subtasks: int = 5
    max_files_per_task: int = 5
    max_dependency_depth: int = 2
    subtasks: list[RunExecutionSubtask] = Field(default_factory=list)


class RunReflectionItem(BaseModel):
    id: str
    ts: datetime | None = None
    title: str
    status: str
    happened: str
    matched_plan: bool | None = None
    changed_next: str | None = None
    files_touched: list[str] = Field(default_factory=list)
    work_item_id: uuid.UUID | None = None
    event_type: str | None = None


class RunWorkingContextSummary(BaseModel):
    goal: str | None = None
    current_step: str | None = None
    next_best_step: str | None = None
    files_touched: list[str] = Field(default_factory=list)
    latest_failure: str | None = None
    validation_state: str | None = None
    review_state: str | None = None
    recovery_count: int = 0
    workspace_status: str | None = None
    branch_name: str | None = None
    confidence_score: float | None = None
    risk_level: str = "LOW"
    pull_request_url: str | None = None


class RunNarrativeResponse(BaseModel):
    run: RunOut
    summary: RunTimelineSummary
    plan: RunPlanSnapshot
    task_decomposition: RunTaskDecomposition
    patch_plan: RunPatchPlan
    verification: RunPatchVerificationSummary
    reflections: list[RunReflectionItem] = Field(default_factory=list)
    working_context: RunWorkingContextSummary
