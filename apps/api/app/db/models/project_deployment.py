from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ProjectDeployment(TimestampMixin, Base):
    __tablename__ = "project_deployments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "request_key", name="uq_project_deployments_request_key"),
        Index("idx_project_deployments_tenant_project_created", "tenant_id", "project_id", "created_at"),
        Index("idx_project_deployments_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="vercel")
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="PREVIEW")
    deployment_strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="static_frontend")
    target: Mapped[str] = mapped_column(String(24), nullable=False, default="user_app")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    request_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_deployment_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deployment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dashboard_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployment_confidence_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rollback_source_deployment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_trigger: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promoted_from_environment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
