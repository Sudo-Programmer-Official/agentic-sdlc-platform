from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class AIJobRun(TimestampMixin, Base):
    __tablename__ = "ai_job_runs"
    __table_args__ = (
        Index("idx_ai_job_runs_project_created", "project_id", "created_at"),
        Index("idx_ai_job_runs_repo_created", "repository_id", "created_at"),
        Index("idx_ai_job_runs_workflow_created", "workflow_type", "created_at"),
        Index("idx_ai_job_runs_tier_created", "selected_model_tier", "created_at"),
        Index("idx_ai_job_runs_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repositories.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    knowledge_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_events.id", ondelete="SET NULL"), nullable=True
    )
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ambiguity_level: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    max_model_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    selected_model_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_state: Mapped[str] = mapped_column(String(16), nullable=False, default="not_required")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class AIArtifactCache(TimestampMixin, Base):
    __tablename__ = "ai_artifact_cache"
    __table_args__ = (
        Index("idx_ai_artifact_cache_project_scope", "project_id", "cache_scope", "updated_at"),
        Index("idx_ai_artifact_cache_repo_scope", "repository_id", "cache_scope", "updated_at"),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "repository_id",
            "cache_scope",
            "cache_key",
            "source_revision",
            name="uq_ai_artifact_cache_scope_key_revision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repositories.id", ondelete="SET NULL"), nullable=True
    )
    cache_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False, default="global")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
