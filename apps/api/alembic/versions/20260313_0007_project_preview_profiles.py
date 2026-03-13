"""project preview profiles

Revision ID: 20260313_0007
Revises: 20260313_0006
Create Date: 2026-03-13 19:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260313_0007"
down_revision = "20260313_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_preview_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("frontend_root", sa.Text(), nullable=True),
        sa.Column("backend_root", sa.Text(), nullable=True),
        sa.Column("compose_file", sa.Text(), nullable=True),
        sa.Column("frontend_build_command", sa.Text(), nullable=True),
        sa.Column("backend_build_command", sa.Text(), nullable=True),
        sa.Column("frontend_start_command", sa.Text(), nullable=True),
        sa.Column("backend_start_command", sa.Text(), nullable=True),
        sa.Column("frontend_healthcheck_path", sa.String(length=255), nullable=True),
        sa.Column("backend_healthcheck_path", sa.String(length=255), nullable=True),
        sa.Column("frontend_port", sa.Integer(), nullable=True),
        sa.Column("backend_port", sa.Integer(), nullable=True),
        sa.Column("env_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ttl_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("max_previews_per_project", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_preview_profiles_project_id"),
    )
    op.create_index(
        "idx_project_preview_profiles_project",
        "project_preview_profiles",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_project_preview_profiles_project", table_name="project_preview_profiles")
    op.drop_table("project_preview_profiles")
