from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecoveryMemoryProfile(Base):
    __tablename__ = "recovery_memory_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "failure_signature",
            "failure_type",
            "recovery_action",
            name="uq_recovery_memory_profile",
        ),
        Index("idx_recovery_memory_lookup", "tenant_id", "project_id", "failure_signature", "failure_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    failure_signature: Mapped[str] = mapped_column(String(256), nullable=False)
    failure_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_action: Mapped[str] = mapped_column(String(64), nullable=False)
    total_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_recovery_attempts: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recommended_model_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
