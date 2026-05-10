"""improvement requests

Revision ID: 20260509_0019
Revises: 20260421_0018
Create Date: 2026-05-09 22:55:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260509_0019"
down_revision: Union[str, None] = "20260421_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "improvement_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("goal_text", sa.Text(), nullable=True),
        sa.Column("issue_text", sa.Text(), nullable=True),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("executor", sa.String(length=32), nullable=True),
        sa.Column("feedback_source", sa.String(length=32), nullable=True),
        sa.Column("start_now", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="CREATED"),
        sa.Column("created_run_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_improvement_requests_project_created",
        "improvement_requests",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index("idx_improvement_requests_source_run", "improvement_requests", ["source_run_id"], unique=False)
    op.create_index("idx_improvement_requests_group", "improvement_requests", ["strategy_group_id"], unique=False)
    op.create_index("idx_improvement_requests_status", "improvement_requests", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_improvement_requests_status", table_name="improvement_requests")
    op.drop_index("idx_improvement_requests_group", table_name="improvement_requests")
    op.drop_index("idx_improvement_requests_source_run", table_name="improvement_requests")
    op.drop_index("idx_improvement_requests_project_created", table_name="improvement_requests")
    op.drop_table("improvement_requests")
