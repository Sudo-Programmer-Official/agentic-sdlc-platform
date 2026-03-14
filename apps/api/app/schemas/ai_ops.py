from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AIOpsSummaryOut(BaseModel):
    total_jobs: int
    calls_per_run: float
    tokens_per_run: float
    cost_per_run: float
    retry_count: int
    success_rate: float
    manual_escalation_rate: float
    approval_rate: float
    average_context_size: float
    total_cost_cents: float
    average_cost_per_successful_pr: float
    average_cost_per_docs_proposal: float


class AIOpsWorkflowMetricOut(BaseModel):
    workflow_type: str
    jobs: int
    calls_per_run: float
    tokens_per_run: float
    cost_per_run: float
    retry_count: int
    average_context_size: float
    success_rate: float
    manual_escalation_rate: float
    approval_rate: float


class AIOpsSpendItemOut(BaseModel):
    key: str
    label: str
    cost_cents: float
    job_count: int


class AIOpsOffenderOut(BaseModel):
    id: uuid.UUID
    label: str
    workflow_type: str
    selected_model_tier: str
    retry_count: int
    context_size: int
    cost_cents: float
    status: str
    created_at: datetime


class AIOpsRecentJobOut(BaseModel):
    id: uuid.UUID
    workflow_type: str
    role: str
    task_type: str
    selected_model_tier: str
    status: str
    approval_state: str
    retry_count: int
    context_size: int
    cost_cents: float
    confidence_score: float | None = None
    requires_human_review: bool
    stop_reason: str | None = None
    project_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AIOpsDashboardOut(BaseModel):
    summary: AIOpsSummaryOut
    workflows: list[AIOpsWorkflowMetricOut]
    spend_by_tier: list[AIOpsSpendItemOut]
    spend_by_project: list[AIOpsSpendItemOut]
    spend_by_repository: list[AIOpsSpendItemOut]
    top_retry_offenders: list[AIOpsOffenderOut]
    largest_context_offenders: list[AIOpsOffenderOut]
    recent_jobs: list[AIOpsRecentJobOut]
