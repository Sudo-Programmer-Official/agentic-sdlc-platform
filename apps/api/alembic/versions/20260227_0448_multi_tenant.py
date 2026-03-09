"""add tenants and tenant_id to core tables

Revision ID: 20260227_0448
Revises: 20260227_0218_workitem_caps
Create Date: 2026-02-27 04:48:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = "20260227_0448"
down_revision = "20260227_0218_workitem_caps"
branch_labels = None
depends_on = None

DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    tables = [
        "projects",
        "documents",
        "tasks",
        "runs",
        "work_items",
        "work_item_edges",
        "artifacts",
        "project_memory",
        "run_events",
        "approvals",
        "traces",
        "activity_logs",
        "agents",
    ]
    for table in tables:
        op.add_column(
            table,
            sa.Column(
                "tenant_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=DEFAULT_TENANT
            ),
        )
        op.create_index(f"ix_{table}_tenant", table, ["tenant_id"])


def downgrade():
    tables = [
        "projects",
        "documents",
        "tasks",
        "runs",
        "work_items",
        "work_item_edges",
        "artifacts",
        "project_memory",
        "run_events",
        "approvals",
        "traces",
        "activity_logs",
        "agents",
    ]
    for table in tables:
        op.drop_index(f"ix_{table}_tenant", table_name=table)
        op.drop_column(table, "tenant_id")
    op.drop_table("tenants")
