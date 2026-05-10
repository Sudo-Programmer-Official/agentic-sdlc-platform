"""task lineage foundation readiness

Revision ID: 20260421_0018
Revises: 20260421_0017
Create Date: 2026-04-21 23:58:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260421_0018"
down_revision: Union[str, None] = "20260421_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"))
    op.add_column("tasks", sa.Column("source_node_id", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("derived_from_requirement_ids", sa.JSON(), nullable=True))
    op.add_column("tasks", sa.Column("capability_id", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("capability_label", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("architecture_slice", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("impact_zone", sa.JSON(), nullable=True))
    op.add_column("tasks", sa.Column("provenance", sa.JSON(), nullable=True))
    op.execute(
        """
        UPDATE tasks
        SET source_type = CASE
            WHEN source = 'ai' THEN 'document_generation'
            WHEN source IS NULL OR source = '' THEN 'manual'
            ELSE source
        END
        """
    )


def downgrade() -> None:
    op.drop_column("tasks", "provenance")
    op.drop_column("tasks", "impact_zone")
    op.drop_column("tasks", "architecture_slice")
    op.drop_column("tasks", "capability_label")
    op.drop_column("tasks", "capability_id")
    op.drop_column("tasks", "derived_from_requirement_ids")
    op.drop_column("tasks", "source_node_id")
    op.drop_column("tasks", "source_type")
