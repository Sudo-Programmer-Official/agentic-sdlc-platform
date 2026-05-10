from __future__ import annotations

import uuid

from sqlalchemy import String, Text, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ImprovementRequest(TimestampMixin, Base):
    __tablename__ = "improvement_requests"
    __table_args__ = (
        Index("idx_improvement_requests_project_created", "project_id", "created_at"),
        Index("idx_improvement_requests_source_run", "source_run_id"),
        Index("idx_improvement_requests_group", "strategy_group_id"),
        Index("idx_improvement_requests_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    source_requirement_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    strategy_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    executor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feedback_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_now: Mapped[bool] = mapped_column(nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED")
    created_run_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resulting_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resulting_pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
