from __future__ import annotations

import uuid

from sqlalchemy import JSON, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class DeploymentProviderConnector(TimestampMixin, Base):
    __tablename__ = "deployment_provider_connectors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "label", name="uq_deploy_connector_label"),
        Index("idx_deploy_connectors_tenant_provider", "tenant_id", "provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    vault_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
