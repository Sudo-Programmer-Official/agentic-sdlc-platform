"""deployment profiles and runtime confidence fields

Revision ID: 20260514_0029
Revises: 20260514_0028
Create Date: 2026-05-14 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260514_0029"
down_revision = "20260514_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_deployments", sa.Column("environment", sa.String(length=16), nullable=False, server_default="PREVIEW"))
    op.add_column("project_deployments", sa.Column("deployment_strategy", sa.String(length=32), nullable=False, server_default="static_frontend"))
    op.add_column("project_deployments", sa.Column("deployment_confidence_score", sa.Float(), nullable=False, server_default="0"))

    op.create_table(
        "deployment_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("deployment_strategy", sa.String(length=32), nullable=False),
        sa.Column("framework", sa.String(length=64), nullable=True),
        sa.Column("install_command", sa.Text(), nullable=True),
        sa.Column("build_command", sa.Text(), nullable=True),
        sa.Column("output_dir", sa.Text(), nullable=True),
        sa.Column("start_command", sa.Text(), nullable=True),
        sa.Column("healthcheck_path", sa.String(length=255), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("runtime_version", sa.String(length=64), nullable=True),
        sa.Column("env_schema", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "project_id", "environment", name="uq_deployment_profiles_project_env"),
    )
    op.create_index("idx_deployment_profiles_tenant_project", "deployment_profiles", ["tenant_id", "project_id"])


def downgrade() -> None:
    op.drop_index("idx_deployment_profiles_tenant_project", table_name="deployment_profiles")
    op.drop_table("deployment_profiles")
    op.drop_column("project_deployments", "deployment_confidence_score")
    op.drop_column("project_deployments", "deployment_strategy")
    op.drop_column("project_deployments", "environment")
