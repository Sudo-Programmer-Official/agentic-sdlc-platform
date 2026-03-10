"""add tenants and tenant_id to core tables

Revision ID: 20260227_0448
Revises: 20260227_0218
Create Date: 2026-02-27 04:48:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260227_0448"
down_revision = "20260227_0218"
branch_labels = None
depends_on = None

DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"


def upgrade():
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
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
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                ADD COLUMN IF NOT EXISTS tenant_id UUID DEFAULT '{DEFAULT_TENANT}'::uuid
                """
            ),
        )
        op.execute(sa.text(f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT}'::uuid WHERE tenant_id IS NULL"))
        op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET DEFAULT '{DEFAULT_TENANT}'::uuid"))
        op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL"))
        op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id)"))


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
        op.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table}_tenant"))
        op.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS tenants"))
