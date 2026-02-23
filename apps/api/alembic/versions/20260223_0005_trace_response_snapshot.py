"""add response_snapshot and provenance fields to traces

Revision ID: 20260223_0005
Revises: 20260223_0004
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260223_0005"
down_revision = "20260223_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("response_snapshot", sa.JSON(), nullable=True))
    op.add_column("traces", sa.Column("temperature", sa.Float(), nullable=True))
    op.add_column("traces", sa.Column("tokens_prompt", sa.Integer(), nullable=True))
    op.add_column("traces", sa.Column("tokens_completion", sa.Integer(), nullable=True))
    op.add_column("traces", sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))


def downgrade() -> None:
    op.drop_column("traces", "generated_at")
    op.drop_column("traces", "tokens_completion")
    op.drop_column("traces", "tokens_prompt")
    op.drop_column("traces", "temperature")
    op.drop_column("traces", "response_snapshot")
