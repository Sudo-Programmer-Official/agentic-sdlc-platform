"""component capability contracts

Revision ID: 20260517_0039
Revises: 20260517_0038
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260517_0039"
down_revision = "20260517_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "component_capability_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("capability", sa.String(length=120), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "environment",
            "capability",
            name="uq_component_capability_project_env_capability",
        ),
    )
    op.create_index(
        "idx_component_capability_project_env",
        "component_capability_contracts",
        ["project_id", "environment"],
    )


def downgrade() -> None:
    op.drop_index("idx_component_capability_project_env", table_name="component_capability_contracts")
    op.drop_table("component_capability_contracts")
