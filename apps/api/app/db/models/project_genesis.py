from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class StackPreset(TimestampMixin, Base):
    __tablename__ = "stack_presets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0), index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    runtime: Mapped[str] = mapped_column(String(120), nullable=False, default="fullstack")
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ProjectBlueprint(TimestampMixin, Base):
    __tablename__ = "project_blueprints"
    __table_args__ = (Index("idx_project_blueprints_project", "tenant_id", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blueprint_key: Mapped[str] = mapped_column(String(120), nullable=False)
    stack_preset_key: Mapped[str] = mapped_column(String(120), nullable=False)
    deployment_profile: Mapped[str] = mapped_column(String(120), nullable=False, default="local_preview")
    architecture: Mapped[str] = mapped_column(String(120), nullable=False, default="fullstack_monorepo")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    readiness_enforced: Mapped[bool] = mapped_column(nullable=False, default=True)
    generated_modules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generated_contracts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ProjectTopologySnapshot(TimestampMixin, Base):
    __tablename__ = "project_topology_snapshots"
    __table_args__ = (Index("idx_project_topology_snapshots_project", "tenant_id", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blueprint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_blueprints.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    topology_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ProjectGenesisRun(TimestampMixin, Base):
    __tablename__ = "project_genesis_runs"
    __table_args__ = (Index("idx_project_genesis_runs_project", "tenant_id", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blueprint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_blueprints.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_task_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
