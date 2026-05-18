from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class CapabilityBinding(TimestampMixin, Base):
    __tablename__ = "capability_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "environment", "capability_key", name="uq_capability_binding_project_env_key"),
        Index("idx_capability_bindings_project_env", "project_id", "environment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="PREVIEW")
    capability_key: Mapped[str] = mapped_column(String(120), nullable=False)
    integration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("capability_integrations.id", ondelete="CASCADE"), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
