from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class CapabilityDefinition(TimestampMixin, Base):
    __tablename__ = "capability_definitions"
    __table_args__ = (
        UniqueConstraint("capability_key", name="uq_capability_definition_key"),
        Index("idx_capability_definition_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supported_providers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
