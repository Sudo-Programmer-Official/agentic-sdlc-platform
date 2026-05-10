from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ProjectEvolutionEvent(Base):
    __tablename__ = "project_evolution_events"
    __table_args__ = (
        Index("idx_project_evolution_events_project_event_at", "project_id", "event_at"),
        Index("idx_project_evolution_events_project_domain_event_at", "project_id", "domain", "event_at"),
        Index("idx_project_evolution_events_project_requirement_event_at", "project_id", "requirement_id", "event_at"),
        Index("idx_project_evolution_events_project_run_event_at", "project_id", "run_id", "event_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="observed")
    requirement_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retention_class: Mapped[str] = mapped_column(String(16), nullable=False, default="keep")
    deployment_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    related_artifact_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    related_file_paths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class MemorySummaryArtifact(TimestampMixin, Base):
    __tablename__ = "memory_summary_artifacts"
    __table_args__ = (
        Index("idx_memory_summary_artifacts_project_type_created", "project_id", "summary_type", "created_at"),
        Index(
            "idx_memory_summary_artifacts_source_version",
            "source_entity_type",
            "source_entity_id",
            "version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    summary_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    window_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
