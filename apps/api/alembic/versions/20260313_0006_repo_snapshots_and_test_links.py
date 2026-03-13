"""add repo snapshots and repo test links

Revision ID: 20260313_0006
Revises: 20260313_0005
Create Date: 2026-03-13 23:58:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260313_0006"
down_revision: Union[str, None] = "20260313_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repo_test_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_file_id", "target_file_id", "relation_type", name="uq_repo_test_links_unique"),
    )
    op.create_index("idx_repo_test_links_project_target", "repo_test_links", ["project_id", "target_file_id"], unique=False)
    op.create_index("idx_repo_test_links_project_test", "repo_test_links", ["project_id", "test_file_id"], unique=False)

    op.create_table(
        "repo_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("test_link_count", sa.Integer(), nullable=False),
        sa.Column("changed_paths", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_repo_snapshots_project_indexed", "repo_snapshots", ["project_id", "indexed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_repo_snapshots_project_indexed", table_name="repo_snapshots")
    op.drop_table("repo_snapshots")
    op.drop_index("idx_repo_test_links_project_test", table_name="repo_test_links")
    op.drop_index("idx_repo_test_links_project_target", table_name="repo_test_links")
    op.drop_table("repo_test_links")
