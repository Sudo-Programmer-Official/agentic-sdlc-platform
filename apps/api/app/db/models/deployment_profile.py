from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class DeploymentProfile(TimestampMixin, Base):
    __tablename__ = "deployment_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "environment", name="uq_deployment_profiles_project_env"),
        Index("idx_deployment_profiles_tenant_project", "tenant_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="PREVIEW")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="vercel")
    deployment_strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="static_frontend")
    framework: Mapped[str | None] = mapped_column(String(64), nullable=True)
    install_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    build_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    healthcheck_path: Mapped[str | None] = mapped_column(String(255), nullable=True, default="/")
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    env_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_connector_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
