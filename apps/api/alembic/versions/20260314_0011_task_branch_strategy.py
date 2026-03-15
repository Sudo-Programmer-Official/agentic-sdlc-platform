"""add task branch strategy fields

Revision ID: 20260314_0011
Revises: 20260314_0010
Create Date: 2026-03-14 19:15:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0011"
down_revision: Union[str, None] = "20260314_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("branch_strategy", sa.String(length=16), nullable=False, server_default="auto"),
    )
    op.add_column("tasks", sa.Column("base_branch", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("branch_name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "branch_name")
    op.drop_column("tasks", "base_branch")
    op.drop_column("tasks", "branch_strategy")
