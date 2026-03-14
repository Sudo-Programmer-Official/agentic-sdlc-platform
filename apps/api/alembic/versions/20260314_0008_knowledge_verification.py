"""knowledge verification subsystem

Revision ID: 20260314_0008
Revises: 20260313_0007
Create Date: 2026-03-14 10:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260314_0008"
down_revision: Union[str, None] = "20260313_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_external_id", sa.String(length=255), nullable=True),
        sa.Column("delivery_key", sa.String(length=255), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column("triggered_by", sa.String(length=120), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="detected"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["project_repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", "delivery_key", name="uq_knowledge_events_repo_delivery"),
        sa.UniqueConstraint("repository_id", "source_type", "source_external_id", name="uq_knowledge_events_repo_source"),
    )
    op.create_index(
        "idx_knowledge_events_project_detected",
        "knowledge_events",
        ["project_id", "detected_at"],
        unique=False,
    )
    op.create_index("idx_knowledge_events_repo_status", "knowledge_events", ["repository_id", "status"], unique=False)

    op.create_table(
        "knowledge_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("technical_summary", sa.Text(), nullable=False),
        sa.Column("business_summary", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("impacts_runtime", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("impacts_api", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("impacts_schema", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("impacts_docs", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("impacts_architecture", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("impacts_onboarding", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("impacted_files", sa.JSON(), nullable=False),
        sa.Column("impacted_modules", sa.JSON(), nullable=False),
        sa.Column("probable_artifacts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_event_id"], ["knowledge_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_knowledge_changes_event", "knowledge_changes", ["knowledge_event_id"], unique=False)
    op.create_index("idx_knowledge_changes_type_risk", "knowledge_changes", ["change_type", "risk_level"], unique=False)

    op.create_table(
        "knowledge_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("canonical_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_by", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["project_repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "repository_id",
            "artifact_type",
            "artifact_key",
            name="uq_knowledge_artifacts_project_key",
        ),
    )
    op.create_index(
        "idx_knowledge_artifacts_project_type",
        "knowledge_artifacts",
        ["project_id", "artifact_type"],
        unique=False,
    )

    op.create_table(
        "knowledge_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposal_type", sa.String(length=32), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("artifact_title", sa.String(length=255), nullable=False),
        sa.Column("target_section", sa.String(length=255), nullable=True),
        sa.Column("generated_content", sa.Text(), nullable=False),
        sa.Column("diff_preview", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_by_agent", sa.String(length=120), nullable=False, server_default="knowledge-engine"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["knowledge_artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["knowledge_event_id"], ["knowledge_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["project_repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_knowledge_proposals_event",
        "knowledge_proposals",
        ["knowledge_event_id", "review_status"],
        unique=False,
    )
    op.create_index(
        "idx_knowledge_proposals_artifact",
        "knowledge_proposals",
        ["artifact_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_user_id", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("edited_content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_knowledge_reviews_proposal_created",
        "knowledge_reviews",
        ["proposal_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("published_content", sa.Text(), nullable=False),
        sa.Column("publication_mode", sa.String(length=32), nullable=False),
        sa.Column("published_by", sa.String(length=120), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["knowledge_artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["knowledge_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_knowledge_publications_artifact_published",
        "knowledge_publications",
        ["artifact_id", "published_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_file_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path_pattern", sa.String(length=1024), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("module_name", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["project_repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id",
            "file_path_pattern",
            "artifact_type",
            "artifact_key",
            name="uq_knowledge_file_mappings_repo_pattern",
        ),
    )
    op.create_index(
        "idx_knowledge_file_mappings_repo_priority",
        "knowledge_file_mappings",
        ["repository_id", "priority"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_file_mappings_repo_priority", table_name="knowledge_file_mappings")
    op.drop_table("knowledge_file_mappings")
    op.drop_index("idx_knowledge_publications_artifact_published", table_name="knowledge_publications")
    op.drop_table("knowledge_publications")
    op.drop_index("idx_knowledge_reviews_proposal_created", table_name="knowledge_reviews")
    op.drop_table("knowledge_reviews")
    op.drop_index("idx_knowledge_proposals_artifact", table_name="knowledge_proposals")
    op.drop_index("idx_knowledge_proposals_event", table_name="knowledge_proposals")
    op.drop_table("knowledge_proposals")
    op.drop_index("idx_knowledge_artifacts_project_type", table_name="knowledge_artifacts")
    op.drop_table("knowledge_artifacts")
    op.drop_index("idx_knowledge_changes_type_risk", table_name="knowledge_changes")
    op.drop_index("idx_knowledge_changes_event", table_name="knowledge_changes")
    op.drop_table("knowledge_changes")
    op.drop_index("idx_knowledge_events_repo_status", table_name="knowledge_events")
    op.drop_index("idx_knowledge_events_project_detected", table_name="knowledge_events")
    op.drop_table("knowledge_events")
