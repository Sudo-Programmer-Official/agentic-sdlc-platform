from __future__ import annotations

import uuid
from sqlalchemy import String, JSON, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ActivityLog(TimestampMixin, Base):
    __tablename__ = "activity_logs"
    __table_args__ = (Index("idx_activity_project_created", "project_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
