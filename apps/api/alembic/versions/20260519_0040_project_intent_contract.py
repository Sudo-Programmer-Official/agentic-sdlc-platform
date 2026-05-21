"""project intent contract

Revision ID: 20260519_0040
Revises: 20260517_0039
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260519_0040"
down_revision = "20260517_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("project_intent_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "project_intent_json")

