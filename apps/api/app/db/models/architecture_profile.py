from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


architecture_json_type = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class ArchitectureProfile(TimestampMixin, Base):
    __tablename__ = "architecture_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_architecture_profiles_project_id"),
        Index("idx_architecture_profiles_tenant", "tenant_id"),
        Index("idx_architecture_profiles_project", "project_id"),
        Index("idx_architecture_profiles_tenant_project", "tenant_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    latest_source_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    repo_full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repo_default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_json: Mapped[dict] = mapped_column(architecture_json_type, nullable=False, default=dict)
    derived_json: Mapped[dict] = mapped_column(architecture_json_type, nullable=False, default=dict)
    last_derived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
