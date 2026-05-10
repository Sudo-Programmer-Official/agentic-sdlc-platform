from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"
    __table_args__ = (
        Index("idx_recovery_attempts_run_created", "run_id", "created_at"),
        Index("idx_recovery_attempts_work_item_attempt", "work_item_id", "attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    failure_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_action: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

