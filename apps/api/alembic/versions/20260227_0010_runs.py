"""add runs table and run_id on tasks

Revision ID: 20260227_0010
Revises: 20260223_0009
Create Date: 2026-02-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260227_0010"
down_revision = "20260223_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="QUEUED"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_runs_project_status", "runs", ["project_id", "status"], unique=False)

    op.add_column("tasks", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_tasks_run", "tasks", "runs", ["run_id"], ["id"], ondelete="SET NULL")
    op.create_index("idx_tasks_run", "tasks", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_tasks_run", table_name="tasks")
    op.drop_constraint("fk_tasks_run", "tasks", type_="foreignkey")
    op.drop_column("tasks", "run_id")
    op.drop_index("idx_runs_project_status", table_name="runs")
    op.drop_table("runs")
