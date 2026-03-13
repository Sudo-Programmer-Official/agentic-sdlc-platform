"""add run summaries read model

Revision ID: 20260313_0004
Revises: 20260313_0003
Create Date: 2026-03-13 18:40:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260313_0004"
down_revision: Union[str, None] = "20260313_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "run_summaries",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("executor", sa.String(length=32), nullable=False),
        sa.Column("branch_name", sa.String(length=120), nullable=True),
        sa.Column("workspace_status", sa.String(length=32), nullable=False),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("recovery_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("changed_files", sa.JSON(), nullable=False),
        sa.Column("artifact_types", sa.JSON(), nullable=False),
        sa.Column("primary_error", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(length=16), nullable=True),
        sa.Column("pr_created", sa.Boolean(), nullable=False),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("run_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("idx_run_summaries_project_created", "run_summaries", ["project_id", "created_at"], unique=False)
    op.create_index("idx_run_summaries_project_status", "run_summaries", ["project_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_run_summaries_project_status", table_name="run_summaries")
    op.drop_index("idx_run_summaries_project_created", table_name="run_summaries")
    op.drop_table("run_summaries")
