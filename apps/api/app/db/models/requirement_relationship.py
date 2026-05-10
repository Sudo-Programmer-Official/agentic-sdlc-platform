from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class RequirementRelationship(TimestampMixin, Base):
    __tablename__ = "requirement_relationships"
    __table_args__ = (
        Index("idx_requirement_relationships_project_from", "project_id", "from_requirement_id"),
        Index("idx_requirement_relationships_project_to", "project_id", "to_requirement_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    from_requirement_id: Mapped[str] = mapped_column(String(120), nullable=False)
    to_requirement_id: Mapped[str] = mapped_column(String(120), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
