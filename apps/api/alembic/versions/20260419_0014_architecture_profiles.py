"""architecture profiles

Revision ID: 20260419_0014
Revises: 20260419_0013
Create Date: 2026-04-19 22:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260419_0014"
down_revision: Union[str, None] = "20260419_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "architecture_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("latest_source_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_full_name", sa.String(length=255), nullable=True),
        sa.Column("repo_default_branch", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("derived_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_derived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_architecture_profiles_project_id"),
    )
    op.create_index("idx_architecture_profiles_tenant", "architecture_profiles", ["tenant_id"], unique=False)
    op.create_index("idx_architecture_profiles_project", "architecture_profiles", ["project_id"], unique=False)
    op.create_index(
        "idx_architecture_profiles_tenant_project",
        "architecture_profiles",
        ["tenant_id", "project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_architecture_profiles_tenant_project", table_name="architecture_profiles")
    op.drop_index("idx_architecture_profiles_project", table_name="architecture_profiles")
    op.drop_index("idx_architecture_profiles_tenant", table_name="architecture_profiles")
    op.drop_table("architecture_profiles")
