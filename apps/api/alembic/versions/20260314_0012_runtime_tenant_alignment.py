"""align runtime lineage tables with tenant schema

Revision ID: 20260314_0012
Revises: 20260314_0011
Create Date: 2026-03-14 22:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260314_0012"
down_revision = "20260314_0011"
branch_labels = None
depends_on = None

DEFAULT_TENANT = "00000000-0000-0000-0000-000000000000"


def _backfill_runtime_table(table: str, parent_table: str, parent_fk: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID"))
    op.execute(
        sa.text(
            f"""
            UPDATE {table} AS child
            SET tenant_id = parent.tenant_id
            FROM {parent_table} AS parent
            WHERE child.{parent_fk} = parent.id
              AND child.tenant_id IS NULL
            """
        )
    )
    op.execute(sa.text(f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT}'::uuid WHERE tenant_id IS NULL"))
    op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET DEFAULT '{DEFAULT_TENANT}'::uuid"))
    op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL"))
    op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id)"))


def upgrade() -> None:
    _backfill_runtime_table("run_memory", "runs", "run_id")
    _backfill_runtime_table("work_item_artifacts", "work_items", "work_item_id")


def downgrade() -> None:
    for table in ("work_item_artifacts", "run_memory"):
        op.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table}_tenant"))
        op.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id"))
