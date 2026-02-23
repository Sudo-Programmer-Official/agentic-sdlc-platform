"""enrich activity log with event_type, previous_state, new_state

Revision ID: 20260223_0008
Revises: 20260223_0007
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260223_0008"
down_revision = "20260223_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activity_logs", sa.Column("event_type", sa.String(length=32), nullable=True))
    op.add_column("activity_logs", sa.Column("previous_state", sa.JSON(), nullable=True))
    op.add_column("activity_logs", sa.Column("new_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("activity_logs", "new_state")
    op.drop_column("activity_logs", "previous_state")
    op.drop_column("activity_logs", "event_type")
