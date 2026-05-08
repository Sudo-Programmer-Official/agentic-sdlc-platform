"""project repository auth strategy

Revision ID: 20260421_0017
Revises: 20260421_0016
Create Date: 2026-04-21 23:45:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260421_0017"
down_revision: Union[str, None] = "20260421_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_repositories",
        sa.Column("auth_strategy", sa.String(length=32), nullable=False, server_default="runtime_default"),
    )
    op.execute(
        """
        UPDATE project_repositories
        SET auth_strategy = CASE
            WHEN repo_url LIKE 'git@%' OR repo_url LIKE 'ssh://%' THEN 'ssh'
            WHEN repo_url LIKE 'https://github.com/%' THEN 'public_https'
            ELSE 'runtime_default'
        END
        WHERE auth_strategy = 'runtime_default'
        """
    )


def downgrade() -> None:
    op.drop_column("project_repositories", "auth_strategy")
