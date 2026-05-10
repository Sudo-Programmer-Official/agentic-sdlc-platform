from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RepoEntity(Base):
    __tablename__ = "repo_entities"
    __table_args__ = (
        UniqueConstraint("project_id", "entity_key", name="uq_repo_entities_project_entity_key"),
        Index("idx_repo_entities_project_kind", "project_id", "entity_kind"),
        Index("idx_repo_entities_project_path", "project_id", "path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_files.id", ondelete="SET NULL"), nullable=True
    )
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_symbols.id", ondelete="SET NULL"), nullable=True
    )
    entity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="module")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RepoOwnership(Base):
    __tablename__ = "repo_ownership"
    __table_args__ = (
        UniqueConstraint("project_id", "owner_type", "owner_id", "entity_id", name="uq_repo_ownership_unique"),
        Index("idx_repo_ownership_project_owner", "project_id", "owner_type", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_entities.id", ondelete="CASCADE"), nullable=False
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False, default="team")
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ownership_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RepoValidation(Base):
    __tablename__ = "repo_validations"
    __table_args__ = (
        Index("idx_repo_validations_project_entity", "project_id", "entity_id"),
        Index("idx_repo_validations_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_entities.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    validation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="test")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RepoChangeHistory(Base):
    __tablename__ = "repo_change_history"
    __table_args__ = (
        Index("idx_repo_change_history_project_created", "project_id", "created_at"),
        Index("idx_repo_change_history_project_entity", "project_id", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_entities.id", ondelete="SET NULL"), nullable=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_files.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False, default="modified")
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    before_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
