"""add activity log table

Revision ID: 20260223_0007
Revises: 20260223_0006
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260223_0007"
down_revision = "20260223_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_activity_project_created", "activity_logs", ["project_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_activity_project_created", table_name="activity_logs")
    op.drop_table("activity_logs")
