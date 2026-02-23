"""rename reserved metadata columns

Revision ID: 20260223_0009
Revises: 20260223_0008
Create Date: 2026-02-23
"""

from __future__ import annotations

from alembic import op


revision = "20260223_0009"
down_revision = "20260223_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("artifacts", "metadata", new_column_name="extra_metadata")
    op.alter_column("activity_logs", "metadata", new_column_name="extra_metadata")


def downgrade() -> None:
    op.alter_column("activity_logs", "extra_metadata", new_column_name="metadata")
    op.alter_column("artifacts", "extra_metadata", new_column_name="metadata")
