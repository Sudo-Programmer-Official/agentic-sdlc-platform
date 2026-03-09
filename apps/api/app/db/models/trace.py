from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, Index, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, SoftDeleteMixin


class Trace(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "traces"
    __table_args__ = (
        Index("idx_traces_from", "from_type", "from_id"),
        Index("idx_traces_to", "to_type", "to_id"),
        Index("idx_traces_project_from_to", "project_id", "from_id", "to_id"),
        Index("idx_traces_project_to_from", "project_id", "to_id", "from_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    from_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_type: Mapped[str] = mapped_column(String(32), nullable=False)
    to_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="relates")
    relation_strength: Mapped[float | None] = mapped_column(nullable=True)
    ai_model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_prompt_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    response_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    tokens_prompt: Mapped[int | None] = mapped_column(nullable=True)
    tokens_completion: Mapped[int | None] = mapped_column(nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
