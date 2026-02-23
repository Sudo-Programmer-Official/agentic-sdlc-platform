"""trace provenance fields and composite indexes

Revision ID: 20260223_0003
Revises: 20260223_0002
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260223_0003"
down_revision = "20260223_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("traces", sa.Column("ai_model_name", sa.String(length=64), nullable=True))
    op.add_column("traces", sa.Column("ai_prompt_hash", sa.String(length=128), nullable=True))
    op.add_column("traces", sa.Column("ai_run_id", sa.String(length=64), nullable=True))
    op.add_column("traces", sa.Column("confidence_score", sa.Float(), nullable=True))

    op.create_index("idx_traces_project_from_to", "traces", ["project_id", "from_id", "to_id"], unique=False)
    op.create_index("idx_traces_project_to_from", "traces", ["project_id", "to_id", "from_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_traces_project_to_from", table_name="traces")
    op.drop_index("idx_traces_project_from_to", table_name="traces")
    op.drop_column("traces", "confidence_score")
    op.drop_column("traces", "ai_run_id")
    op.drop_column("traces", "ai_prompt_hash")
    op.drop_column("traces", "ai_model_name")
    op.drop_column("traces", "project_id")
