"""add persistent repo intelligence tables

Revision ID: 20260313_0005
Revises: 20260313_0004
Create Date: 2026-03-13 23:40:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260313_0005"
down_revision: Union[str, None] = "20260313_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repo_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "path", name="uq_repo_files_project_path"),
    )
    op.create_index("idx_repo_files_project_kind", "repo_files", ["project_id", "kind"], unique=False)
    op.create_index("idx_repo_files_project_path", "repo_files", ["project_id", "path"], unique=False)

    op.create_table(
        "repo_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "name", "type", "line_start", name="uq_repo_symbols_file_symbol"),
    )
    op.create_index("idx_repo_symbols_project_name", "repo_symbols", ["project_id", "name"], unique=False)
    op.create_index("idx_repo_symbols_project_type", "repo_symbols", ["project_id", "type"], unique=False)

    op.create_table(
        "repo_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_file_id", "target_file_id", "relation_type", name="uq_repo_edges_unique"),
    )
    op.create_index("idx_repo_edges_project_source", "repo_edges", ["project_id", "source_file_id"], unique=False)
    op.create_index("idx_repo_edges_project_target", "repo_edges", ["project_id", "target_file_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_repo_edges_project_target", table_name="repo_edges")
    op.drop_index("idx_repo_edges_project_source", table_name="repo_edges")
    op.drop_table("repo_edges")
    op.drop_index("idx_repo_symbols_project_type", table_name="repo_symbols")
    op.drop_index("idx_repo_symbols_project_name", table_name="repo_symbols")
    op.drop_table("repo_symbols")
    op.drop_index("idx_repo_files_project_path", table_name="repo_files")
    op.drop_index("idx_repo_files_project_kind", table_name="repo_files")
    op.drop_table("repo_files")
