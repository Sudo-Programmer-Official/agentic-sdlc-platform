"""project deployments for one-click delivery

Revision ID: 20260514_0028
Revises: 20260510_0027
Create Date: 2026-05-14 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260514_0028"
down_revision = "20260510_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("request_key", sa.String(length=120), nullable=True),
        sa.Column("external_deployment_id", sa.String(length=120), nullable=True),
        sa.Column("deployment_url", sa.Text(), nullable=True),
        sa.Column("dashboard_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "project_id", "request_key", name="uq_project_deployments_request_key"),
    )
    op.create_index(
        "idx_project_deployments_tenant_project_created",
        "project_deployments",
        ["tenant_id", "project_id", "created_at"],
    )
    op.create_index("idx_project_deployments_run", "project_deployments", ["run_id"])


def downgrade() -> None:
    op.drop_index("idx_project_deployments_run", table_name="project_deployments")
    op.drop_index("idx_project_deployments_tenant_project_created", table_name="project_deployments")
    op.drop_table("project_deployments")
