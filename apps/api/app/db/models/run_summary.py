from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class RunSummary(TimestampMixin, Base):
    __tablename__ = "run_summaries"
    __table_args__ = (
        Index("idx_run_summaries_project_created", "project_id", "created_at"),
        Index("idx_run_summaries_project_status", "project_id", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    executor: Mapped[str] = mapped_column(String(32), nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    workspace_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    artifact_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    primary_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pr_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
