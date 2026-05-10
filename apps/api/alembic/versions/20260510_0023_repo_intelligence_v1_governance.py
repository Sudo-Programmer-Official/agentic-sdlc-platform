"""repo intelligence v1 governance

Revision ID: 20260510_0023
Revises: 20260509_0022
Create Date: 2026-05-10 10:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260510_0023"
down_revision = "20260509_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repo_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_key", sa.String(length=512), nullable=False),
        sa.Column("entity_kind", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["repo_symbols.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "entity_key", name="uq_repo_entities_project_entity_key"),
    )
    op.create_index("idx_repo_entities_project_kind", "repo_entities", ["project_id", "entity_kind"])
    op.create_index("idx_repo_entities_project_path", "repo_entities", ["project_id", "path"])

    op.create_table(
        "repo_ownership",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("ownership_score", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["repo_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "owner_type", "owner_id", "entity_id", name="uq_repo_ownership_unique"),
    )
    op.create_index("idx_repo_ownership_project_owner", "repo_ownership", ["project_id", "owner_type", "owner_id"])

    op.create_table(
        "repo_validations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("validation_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["repo_entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_repo_validations_project_entity", "repo_validations", ["project_id", "entity_id"])
    op.create_index("idx_repo_validations_project_status", "repo_validations", ["project_id", "status"])

    op.create_table(
        "repo_change_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("before_checksum", sa.String(length=64), nullable=True),
        sa.Column("after_checksum", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["repo_entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["repo_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_repo_change_history_project_created", "repo_change_history", ["project_id", "created_at"])
    op.create_index("idx_repo_change_history_project_entity", "repo_change_history", ["project_id", "entity_id"])


def downgrade() -> None:
    op.drop_index("idx_repo_change_history_project_entity", table_name="repo_change_history")
    op.drop_index("idx_repo_change_history_project_created", table_name="repo_change_history")
    op.drop_table("repo_change_history")

    op.drop_index("idx_repo_validations_project_status", table_name="repo_validations")
    op.drop_index("idx_repo_validations_project_entity", table_name="repo_validations")
    op.drop_table("repo_validations")

    op.drop_index("idx_repo_ownership_project_owner", table_name="repo_ownership")
    op.drop_table("repo_ownership")

    op.drop_index("idx_repo_entities_project_path", table_name="repo_entities")
    op.drop_index("idx_repo_entities_project_kind", table_name="repo_entities")
    op.drop_table("repo_entities")
