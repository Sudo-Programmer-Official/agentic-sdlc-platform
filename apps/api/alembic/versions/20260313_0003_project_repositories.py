"""add project repositories

Revision ID: 20260313_0003
Revises: 20260313_0002
Create Date: 2026-03-13 13:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260313_0003"
down_revision: Union[str, None] = "20260313_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("repo_url", sa.Text(), nullable=False),
        sa.Column("repo_full_name", sa.String(length=255), nullable=True),
        sa.Column("default_branch", sa.String(length=120), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_repositories_project_id"),
    )
    op.create_index("idx_project_repositories_project", "project_repositories", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_project_repositories_project", table_name="project_repositories")
    op.drop_table("project_repositories")
