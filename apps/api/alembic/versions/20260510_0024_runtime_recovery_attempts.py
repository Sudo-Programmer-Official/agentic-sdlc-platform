"""runtime recovery attempts

Revision ID: 20260510_0024
Revises: 20260510_0023
Create Date: 2026-05-10 11:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260510_0024"
down_revision = "20260510_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_type", sa.String(length=64), nullable=False),
        sa.Column("recovery_action", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("result", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_recovery_attempts_run_created", "recovery_attempts", ["run_id", "created_at"])
    op.create_index("idx_recovery_attempts_work_item_attempt", "recovery_attempts", ["work_item_id", "attempt_number"])


def downgrade() -> None:
    op.drop_index("idx_recovery_attempts_work_item_attempt", table_name="recovery_attempts")
    op.drop_index("idx_recovery_attempts_run_created", table_name="recovery_attempts")
    op.drop_table("recovery_attempts")
