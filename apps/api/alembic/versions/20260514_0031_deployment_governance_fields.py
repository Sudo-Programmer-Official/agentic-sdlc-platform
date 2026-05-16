"""deployment governance fields for rollback/promotion

Revision ID: 20260514_0031
Revises: 20260514_0030
Create Date: 2026-05-14 14:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260514_0031"
down_revision = "20260514_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_deployments", sa.Column("rollback_source_deployment_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("project_deployments", sa.Column("rollback_reason", sa.Text(), nullable=True))
    op.add_column("project_deployments", sa.Column("rollback_trigger", sa.String(length=64), nullable=True))
    op.add_column("project_deployments", sa.Column("promoted_from_environment", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("project_deployments", "promoted_from_environment")
    op.drop_column("project_deployments", "rollback_trigger")
    op.drop_column("project_deployments", "rollback_reason")
    op.drop_column("project_deployments", "rollback_source_deployment_id")
