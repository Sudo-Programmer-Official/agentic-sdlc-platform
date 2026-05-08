"""project contracts

Revision ID: 20260421_0016
Revises: 20260420_0015
Create Date: 2026-04-21 23:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260421_0016"
down_revision: Union[str, None] = "20260420_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("contract_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("derived_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_derived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_contracts_project_id"),
    )
    op.create_index("idx_project_contracts_tenant", "project_contracts", ["tenant_id"], unique=False)
    op.create_index("idx_project_contracts_project", "project_contracts", ["project_id"], unique=False)
    op.create_index(
        "idx_project_contracts_tenant_project",
        "project_contracts",
        ["tenant_id", "project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_project_contracts_tenant_project", table_name="project_contracts")
    op.drop_index("idx_project_contracts_project", table_name="project_contracts")
    op.drop_index("idx_project_contracts_tenant", table_name="project_contracts")
    op.drop_table("project_contracts")
