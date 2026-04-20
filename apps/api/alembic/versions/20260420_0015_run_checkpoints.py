"""durable run checkpoints

Revision ID: 20260420_0015
Revises: 20260419_0014
Create Date: 2026-04-20 10:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260420_0015"
down_revision: Union[str, None] = "20260419_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "run_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="safe"),
        sa.Column("work_item_type", sa.String(length=32), nullable=True),
        sa.Column("work_item_status", sa.String(length=16), nullable=True),
        sa.Column("storage_mode", sa.String(length=24), nullable=False, server_default="metadata_only"),
        sa.Column(
            "dirty_files",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("dirty_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("patch_blob", sa.LargeBinary(), nullable=True),
        sa.Column("patch_sha256", sa.String(length=64), nullable=True),
        sa.Column("patch_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workspace_patch_path", sa.Text(), nullable=True),
        sa.Column("workspace_patch_uri", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_run_checkpoints_run_created", "run_checkpoints", ["run_id", "created_at"], unique=False)
    op.create_index("idx_run_checkpoints_project_run", "run_checkpoints", ["project_id", "run_id"], unique=False)
    op.create_index("idx_run_checkpoints_checkpoint_id", "run_checkpoints", ["checkpoint_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_run_checkpoints_checkpoint_id", table_name="run_checkpoints")
    op.drop_index("idx_run_checkpoints_project_run", table_name="run_checkpoints")
    op.drop_index("idx_run_checkpoints_run_created", table_name="run_checkpoints")
    op.drop_table("run_checkpoints")
