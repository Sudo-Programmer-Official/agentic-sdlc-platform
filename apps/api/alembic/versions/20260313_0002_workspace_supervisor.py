"""add workspace supervisor fields to runs

Revision ID: 20260313_0002
Revises: 20260311_0001
Create Date: 2026-03-13 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260313_0002"
down_revision: Union[str, None] = "20260311_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("workspace_root", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("repo_path", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("branch_name", sa.String(length=120), nullable=True))
    op.add_column(
        "runs",
        sa.Column("workspace_status", sa.String(length=32), nullable=False, server_default="PENDING"),
    )
    op.add_column("runs", sa.Column("workspace_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "workspace_error")
    op.drop_column("runs", "workspace_status")
    op.drop_column("runs", "branch_name")
    op.drop_column("runs", "repo_path")
    op.drop_column("runs", "workspace_root")
