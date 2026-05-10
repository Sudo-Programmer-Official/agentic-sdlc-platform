from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class RequirementMemory(TimestampMixin, Base):
    __tablename__ = "requirement_memories"
    __table_args__ = (
        Index("idx_requirement_memories_project_req", "project_id", "requirement_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(String(120), nullable=False)
    compact_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    historical_patterns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    prior_successful_fixes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recurring_failures: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    architectural_constraints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_patterns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
