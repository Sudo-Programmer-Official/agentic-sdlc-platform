from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


project_contract_json_type = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class ProjectContract(TimestampMixin, Base):
    __tablename__ = "project_contracts"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_contracts_project_id"),
        Index("idx_project_contracts_tenant", "tenant_id"),
        Index("idx_project_contracts_project", "project_id"),
        Index("idx_project_contracts_tenant_project", "tenant_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_json: Mapped[dict] = mapped_column(project_contract_json_type, nullable=False, default=dict)
    derived_json: Mapped[dict] = mapped_column(project_contract_json_type, nullable=False, default=dict)
    last_derived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
