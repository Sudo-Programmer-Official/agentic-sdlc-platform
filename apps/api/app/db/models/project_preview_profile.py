from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


preview_env_type = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class ProjectPreviewProfile(TimestampMixin, Base):
    __tablename__ = "project_preview_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_preview_profiles_project_id"),
        Index("idx_project_preview_profiles_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    frontend_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    backend_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    compose_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    frontend_build_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    backend_build_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    frontend_start_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    backend_start_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    frontend_healthcheck_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backend_healthcheck_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frontend_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backend_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    env_overrides: Mapped[dict | None] = mapped_column(preview_env_type, nullable=True)
    ttl_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    max_previews_per_project: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
