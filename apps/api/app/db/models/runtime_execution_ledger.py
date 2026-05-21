from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunLedger(Base):
    __tablename__ = "run_ledger"
    __table_args__ = (
        Index("idx_run_ledger_run_created", "run_id", "created_at"),
        Index("idx_run_ledger_project_created", "project_id", "created_at"),
        Index("idx_run_ledger_customer_created", "customer_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="RUN_AGGREGATE_SNAPSHOT")
    feature_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capability_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_overhead_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    preview_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drift_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StageLedger(Base):
    __tablename__ = "stage_ledger"
    __table_args__ = (
        Index("idx_stage_ledger_run_stage_created", "run_id", "stage_name", "created_at"),
        Index("idx_stage_ledger_work_item_created", "work_item_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    files_touched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    package_affinity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    layer_affinity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topology_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    architecture_compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CostLedger(Base):
    __tablename__ = "cost_ledger"
    __table_args__ = (
        Index("idx_cost_ledger_run_stage_created", "run_id", "stage_name", "created_at"),
        Index("idx_cost_ledger_feature_created", "feature_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capability_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wall_clock_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_cost_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_amplification_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PatchLedger(Base):
    __tablename__ = "patch_ledger"
    __table_args__ = (
        Index("idx_patch_ledger_run_stage_created", "run_id", "stage_name", "created_at"),
        Index("idx_patch_ledger_risk_created", "risk_score", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    files_touched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    patch_entropy: Mapped[float | None] = mapped_column(Float, nullable=True)
    monolith_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    drift_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    package_affinity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    layer_affinity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topology_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    architecture_compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecoveryLedger(Base):
    __tablename__ = "recovery_ledger"
    __table_args__ = (
        Index("idx_recovery_ledger_run_created", "run_id", "created_at"),
        Index("idx_recovery_ledger_stage_created", "stage_name", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    stage_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    convergence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_progress_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_waste_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
