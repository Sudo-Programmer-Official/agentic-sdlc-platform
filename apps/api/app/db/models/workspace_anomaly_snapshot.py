from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceAnomalySnapshot(Base):
    __tablename__ = "workspace_anomaly_snapshots"
    __table_args__ = (
        UniqueConstraint("workspace_id", "window_days", "snapshot_date", name="uq_workspace_anomaly_snapshot"),
        Index("idx_workspace_anomaly_workspace_date", "workspace_id", "snapshot_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    runs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recoveries_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    burn_spike: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_spike: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    burn_ratio: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_ratio: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
