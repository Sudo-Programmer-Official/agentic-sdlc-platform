"""add trace, artifact, approval tables and soft delete

Revision ID: 20260223_0002
Revises: 20260223_0001
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260223_0002"
down_revision = "20260223_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # soft delete columns
    for table in ("projects", "documents", "tasks"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # artifacts
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_artifacts_project", "artifacts", ["project_id"], unique=False)

    # traces
    op.create_table(
        "traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_type", sa.String(length=32), nullable=False),
        sa.Column("from_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_type", sa.String(length=32), nullable=False),
        sa.Column("to_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="relates"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_traces_from", "traces", ["from_type", "from_id"], unique=False)
    op.create_index("idx_traces_to", "traces", ["to_type", "to_id"], unique=False)

    # approvals
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.Column("decided_at", sa.String(length=100), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_approvals_target", "approvals", ["target_type", "target_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_approvals_target", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("idx_traces_to", table_name="traces")
    op.drop_index("idx_traces_from", table_name="traces")
    op.drop_table("traces")
    op.drop_index("idx_artifacts_project", table_name="artifacts")
    op.drop_table("artifacts")

    for table in ("tasks", "documents", "projects"):
        op.drop_column(table, "deleted_at")
