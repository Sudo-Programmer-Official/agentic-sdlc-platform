from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, JSON, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class RunCheckpoint(TimestampMixin, Base):
    __tablename__ = "run_checkpoints"
    __table_args__ = (
        Index("idx_run_checkpoints_run_created", "run_id", "created_at"),
        Index("idx_run_checkpoints_project_run", "project_id", "run_id"),
        Index("idx_run_checkpoints_checkpoint_id", "checkpoint_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    checkpoint_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="safe")
    work_item_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    work_item_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    storage_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="metadata_only")
    dirty_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dirty_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    patch_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    patch_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    patch_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workspace_patch_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_patch_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
