"""deployment provider connectors and profile linkage

Revision ID: 20260514_0030
Revises: 20260514_0029
Create Date: 2026-05-14 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260514_0030"
down_revision = "20260514_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_provider_connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("vault_ref", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider", "label", name="uq_deploy_connector_label"),
    )
    op.create_index(
        "idx_deploy_connectors_tenant_provider",
        "deployment_provider_connectors",
        ["tenant_id", "provider"],
    )

    op.add_column("deployment_profiles", sa.Column("provider_connector_id", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment_profiles", "provider_connector_id")
    op.drop_index("idx_deploy_connectors_tenant_provider", table_name="deployment_provider_connectors")
    op.drop_table("deployment_provider_connectors")
