from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, SoftDeleteMixin


class Task(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("idx_tasks_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    generated_from_document_version: Mapped[int | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), default="func", nullable=False)
    stage: Mapped[str] = mapped_column(String(16), default="PLAN", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
