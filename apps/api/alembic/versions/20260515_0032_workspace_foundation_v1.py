"""workspace foundation v1

Revision ID: 20260515_0032
Revises: 20260514_0031
Create Date: 2026-05-15 09:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260515_0032"
down_revision = "20260514_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_workspaces_tenant"),
    )

    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),
    )

    op.add_column("projects", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("deployment_profiles", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("deployment_provider_connectors", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.execute(
        """
        INSERT INTO workspaces (id, tenant_id, name)
        SELECT id, id, name FROM tenants
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO workspace_members (id, workspace_id, user_id, role)
        SELECT tm.id, tm.tenant_id, tm.user_id, tm.role
        FROM tenant_members tm
        """
    )

    op.execute("UPDATE projects SET workspace_id = tenant_id WHERE workspace_id IS NULL")
    op.execute("""
        UPDATE deployment_profiles dp
        SET workspace_id = p.workspace_id
        FROM projects p
        WHERE dp.project_id = p.id
    """)
    op.execute("UPDATE deployment_provider_connectors SET workspace_id = tenant_id WHERE workspace_id IS NULL")


def downgrade() -> None:
    op.drop_column("deployment_provider_connectors", "workspace_id")
    op.drop_column("deployment_profiles", "workspace_id")
    op.drop_column("projects", "workspace_id")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
