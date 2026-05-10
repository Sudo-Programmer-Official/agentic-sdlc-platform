"""recovery memory profiles

Revision ID: 20260510_0025
Revises: 20260510_0024
Create Date: 2026-05-10 11:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260510_0025"
down_revision = "20260510_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_memory_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("failure_signature", sa.String(length=256), nullable=False),
        sa.Column("failure_type", sa.String(length=64), nullable=False),
        sa.Column("recovery_action", sa.String(length=64), nullable=False),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_recovery_attempts", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recommended_model_tier", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "failure_signature",
            "failure_type",
            "recovery_action",
            name="uq_recovery_memory_profile",
        ),
    )
    op.create_index(
        "idx_recovery_memory_lookup",
        "recovery_memory_profiles",
        ["tenant_id", "project_id", "failure_signature", "failure_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_recovery_memory_lookup", table_name="recovery_memory_profiles")
    op.drop_table("recovery_memory_profiles")
