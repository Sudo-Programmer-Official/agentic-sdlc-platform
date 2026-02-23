"""add content_hash to documents and generated_from_document_version to tasks

Revision ID: 20260223_0006
Revises: 20260223_0005
Create Date: 2026-02-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260223_0006"
down_revision = "20260223_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("generated_from_document_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "generated_from_document_version")
    op.drop_column("documents", "content_hash")
