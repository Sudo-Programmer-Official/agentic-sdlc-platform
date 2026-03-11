"""add runtime lineage columns for run events and artifacts

Revision ID: 20260311_0001
Revises: 20260227_0448
Create Date: 2026-03-11 00:01:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260311_0001"
down_revision = "20260227_0448"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_events", sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_run_events_work_item_id_work_items",
        "run_events",
        "work_items",
        ["work_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_run_events_work_item_ts", "run_events", ["work_item_id", "ts"], unique=False)

    op.add_column("artifacts", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("artifacts", sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_artifacts_run_id_runs",
        "artifacts",
        "runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_artifacts_work_item_id_work_items",
        "artifacts",
        "work_items",
        ["work_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_artifacts_run", "artifacts", ["run_id"], unique=False)
    op.create_index("idx_artifacts_work_item", "artifacts", ["work_item_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_artifacts_work_item", table_name="artifacts")
    op.drop_index("idx_artifacts_run", table_name="artifacts")
    op.drop_constraint("fk_artifacts_work_item_id_work_items", "artifacts", type_="foreignkey")
    op.drop_constraint("fk_artifacts_run_id_runs", "artifacts", type_="foreignkey")
    op.drop_column("artifacts", "work_item_id")
    op.drop_column("artifacts", "run_id")

    op.drop_index("idx_run_events_work_item_ts", table_name="run_events")
    op.drop_constraint("fk_run_events_work_item_id_work_items", "run_events", type_="foreignkey")
    op.drop_column("run_events", "work_item_id")
