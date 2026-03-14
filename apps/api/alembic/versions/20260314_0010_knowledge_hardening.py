"""harden knowledge proposal lifecycle and idempotency

Revision ID: 20260314_0010
Revises: 20260314_0009
Create Date: 2026-03-14 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260314_0010"
down_revision: Union[str, None] = "20260314_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMPTY_CONTENT_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def upgrade() -> None:
    op.add_column(
        "knowledge_proposals",
        sa.Column("base_artifact_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_proposals",
        sa.Column(
            "base_artifact_hash",
            sa.String(length=64),
            nullable=False,
            server_default=EMPTY_CONTENT_HASH,
        ),
    )
    op.create_unique_constraint(
        "uq_knowledge_publications_proposal_id",
        "knowledge_publications",
        ["proposal_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_knowledge_publications_proposal_id",
        "knowledge_publications",
        type_="unique",
    )
    op.drop_column("knowledge_proposals", "base_artifact_hash")
    op.drop_column("knowledge_proposals", "base_artifact_version")
