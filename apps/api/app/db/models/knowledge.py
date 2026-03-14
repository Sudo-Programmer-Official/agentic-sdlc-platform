from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class KnowledgeEvent(TimestampMixin, Base):
    __tablename__ = "knowledge_events"
    __table_args__ = (
        Index("idx_knowledge_events_project_detected", "project_id", "detected_at"),
        Index("idx_knowledge_events_repo_status", "repository_id", "status"),
        UniqueConstraint("repository_id", "delivery_key", name="uq_knowledge_events_repo_delivery"),
        UniqueConstraint("repository_id", "source_type", "source_external_id", name="uq_knowledge_events_repo_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repositories.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="detected")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeChange(Base):
    __tablename__ = "knowledge_changes"
    __table_args__ = (
        Index("idx_knowledge_changes_event", "knowledge_event_id"),
        Index("idx_knowledge_changes_type_risk", "change_type", "risk_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_events.id", ondelete="CASCADE"), nullable=False
    )
    change_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    technical_summary: Mapped[str] = mapped_column(Text, nullable=False)
    business_summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    impacts_runtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impacts_api: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impacts_schema: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impacts_docs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impacts_architecture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impacts_onboarding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    impacted_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    impacted_modules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    probable_artifacts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeArtifact(TimestampMixin, Base):
    __tablename__ = "knowledge_artifacts"
    __table_args__ = (
        Index("idx_knowledge_artifacts_project_type", "project_id", "artifact_type"),
        UniqueConstraint(
            "project_id",
            "repository_id",
            "artifact_type",
            "artifact_key",
            name="uq_knowledge_artifacts_project_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repositories.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class KnowledgeProposal(TimestampMixin, Base):
    __tablename__ = "knowledge_proposals"
    __table_args__ = (
        Index("idx_knowledge_proposals_event", "knowledge_event_id", "review_status"),
        Index("idx_knowledge_proposals_artifact", "artifact_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repositories.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_events.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    proposal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_title: Mapped[str] = mapped_column(String(255), nullable=False)
    target_section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_content: Mapped[str] = mapped_column(Text, nullable=False)
    diff_preview: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    base_artifact_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    base_artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_by_agent: Mapped[str] = mapped_column(String(120), nullable=False, default="knowledge-engine")


class KnowledgeReview(Base):
    __tablename__ = "knowledge_reviews"
    __table_args__ = (Index("idx_knowledge_reviews_proposal_created", "proposal_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_proposals.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgePublication(Base):
    __tablename__ = "knowledge_publications"
    __table_args__ = (
        Index("idx_knowledge_publications_artifact_published", "artifact_id", "published_at"),
        UniqueConstraint("proposal_id", name="uq_knowledge_publications_proposal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_proposals.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    published_content: Mapped[str] = mapped_column(Text, nullable=False)
    publication_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeFileMapping(Base):
    __tablename__ = "knowledge_file_mappings"
    __table_args__ = (
        Index("idx_knowledge_file_mappings_repo_priority", "repository_id", "priority"),
        UniqueConstraint(
            "repository_id",
            "file_path_pattern",
            "artifact_type",
            "artifact_key",
            name="uq_knowledge_file_mappings_repo_pattern",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.UUID(int=0))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_repositories.id", ondelete="CASCADE"), nullable=False
    )
    file_path_pattern: Mapped[str] = mapped_column(String(1024), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    module_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
