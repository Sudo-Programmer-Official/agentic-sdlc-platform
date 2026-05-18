"""capability runtime registries and bindings

Revision ID: 20260517_0038
Revises: 20260517_0037
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260517_0038"
down_revision = "20260517_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_key", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("supported_providers", sa.JSON(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability_key", name="uq_capability_definition_key"),
    )
    op.create_index("idx_capability_definition_category", "capability_definitions", ["category"])

    op.create_table(
        "capability_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("health_status", sa.String(length=24), nullable=False),
        sa.Column("credentials_vault_ref", sa.String(length=255), nullable=True),
        sa.Column("connector_ref", sa.String(length=120), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("last_successful_call_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.Column("retry_state", sa.String(length=24), nullable=True),
        sa.Column("environment_sync_state", sa.String(length=24), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_capability_integrations_project_env", "capability_integrations", ["project_id", "environment"])
    op.create_index("idx_capability_integrations_tenant_provider", "capability_integrations", ["tenant_id", "provider"])

    op.create_table(
        "capability_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("capability_key", sa.String(length=120), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["capability_integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "environment", "capability_key", name="uq_capability_binding_project_env_key"),
    )
    op.create_index("idx_capability_bindings_project_env", "capability_bindings", ["project_id", "environment"])


def downgrade() -> None:
    op.drop_index("idx_capability_bindings_project_env", table_name="capability_bindings")
    op.drop_table("capability_bindings")

    op.drop_index("idx_capability_integrations_tenant_provider", table_name="capability_integrations")
    op.drop_index("idx_capability_integrations_project_env", table_name="capability_integrations")
    op.drop_table("capability_integrations")

    op.drop_index("idx_capability_definition_category", table_name="capability_definitions")
    op.drop_table("capability_definitions")
