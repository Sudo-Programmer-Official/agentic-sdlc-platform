from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TrainingExampleFeaturesOut(BaseModel):
    task_type: str | None = None
    package_affinity: str | None = None
    layer_affinity: str | None = None
    topology_zone: str | None = None
    target_file_count: int = 0
    model_tier: str | None = None
    feature_key: str | None = None
    capability_key: str | None = None
    customer_key: str | None = None
    repository_state: str | None = None
    executor: str | None = None
    expected_stage_count: int = 0
    expected_files_count: int = 0
    expected_components: int = 0
    expected_backend_modules: int = 0
    predicted_risk: str | None = None
    predicted_cost_min_cents: float | None = None
    predicted_cost_max_cents: float | None = None
    predicted_duration_min_seconds: float | None = None
    predicted_duration_max_seconds: float | None = None


class TrainingExampleLabelsOut(BaseModel):
    run_status: str
    success: bool
    total_cost_cents: float
    total_duration_ms: int
    recovery_overhead_pct: float
    recovery_overhead: float = 0.0
    preview_passed: bool = False
    preview_failures: int
    drift_events: int
    run_recovery_events: int
    run_retries: int
    architecture_compliance_score: float | None = None


class TrainingExampleOut(BaseModel):
    run_id: uuid.UUID
    project_id: uuid.UUID
    features: TrainingExampleFeaturesOut
    labels: TrainingExampleLabelsOut
    stage_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_files_touched: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    created_at: datetime


class TrainingExampleResponse(BaseModel):
    items: list[TrainingExampleOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
