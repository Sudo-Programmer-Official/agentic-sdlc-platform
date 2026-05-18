from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class CapabilityIntegration(TimestampMixin, Base):
    __tablename__ = "capability_integrations"
    __table_args__ = (
        Index("idx_capability_integrations_project_env", "project_id", "environment"),
        Index("idx_capability_integrations_tenant_provider", "tenant_id", "provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="PREVIEW")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CONNECTED")
    capabilities: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    health_status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN")
    credentials_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connector_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    last_successful_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    environment_sync_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
