"""add relation_strength to traces

Revision ID: 20260223_0004
Revises: 20260223_0003
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260223_0004"
down_revision = "20260223_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("relation_strength", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("traces", "relation_strength")
