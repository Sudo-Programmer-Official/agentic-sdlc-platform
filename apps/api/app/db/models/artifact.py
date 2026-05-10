from __future__ import annotations

import uuid
from sqlalchemy import ForeignKey, String, Text, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, SoftDeleteMixin


class Artifact(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("idx_artifacts_project", "project_id"),
        Index("idx_artifacts_run", "run_id"),
        Index("idx_artifacts_work_item", "work_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    requirement_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
