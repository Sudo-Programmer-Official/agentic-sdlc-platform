from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EstimationFeatureSnapshot(Base):
    __tablename__ = "estimation_features"
    __table_args__ = (
        Index("idx_estimation_features_project_created", "project_id", "created_at"),
        Index("idx_estimation_features_run_created", "run_id", "created_at"),
        Index("idx_estimation_features_feature_key", "feature_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, default="PRE_RUN")
    feature_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capability_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    repository_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_stage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_components: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_backend_modules: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    predicted_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    predicted_cost_min_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_cost_max_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_duration_min_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_duration_max_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EstimationOutcomeSnapshot(Base):
    __tablename__ = "estimation_outcomes"
    __table_args__ = (
        Index("idx_estimation_outcomes_project_created", "project_id", "created_at"),
        Index("idx_estimation_outcomes_run_created", "run_id", "created_at"),
        Index("idx_estimation_outcomes_status_created", "run_status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, default="POST_RUN")
    run_status: Mapped[str] = mapped_column(String(16), nullable=False)
    success: Mapped[bool] = mapped_column(nullable=False, default=False)
    total_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_overhead_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    preview_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drift_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_recovery_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    architecture_compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
