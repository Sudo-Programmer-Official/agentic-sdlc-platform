"""task requirement linkage

Revision ID: 20260509_0020
Revises: 20260509_0019
Create Date: 2026-05-09 18:12:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260509_0020"
down_revision = "20260509_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("requirement_id", sa.String(length=120), nullable=True))
    op.create_index("ix_tasks_requirement_id", "tasks", ["requirement_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_requirement_id", table_name="tasks")
    op.drop_column("tasks", "requirement_id")
