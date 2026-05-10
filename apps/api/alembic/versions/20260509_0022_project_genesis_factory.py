"""project genesis factory

Revision ID: 20260509_0022
Revises: 20260509_0021
Create Date: 2026-05-09 18:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260509_0022"
down_revision = "20260509_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stack_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("runtime", sa.String(length=120), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stack_presets_tenant_id", "stack_presets", ["tenant_id"])

    op.create_table(
        "project_blueprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blueprint_key", sa.String(length=120), nullable=False),
        sa.Column("stack_preset_key", sa.String(length=120), nullable=False),
        sa.Column("deployment_profile", sa.String(length=120), nullable=False),
        sa.Column("architecture", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("readiness_enforced", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("generated_modules", sa.JSON(), nullable=True),
        sa.Column("generated_contracts", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_blueprints_tenant_id", "project_blueprints", ["tenant_id"])
    op.create_index("ix_project_blueprints_project_id", "project_blueprints", ["project_id"])
    op.create_index("idx_project_blueprints_project", "project_blueprints", ["tenant_id", "project_id"])

    op.create_table(
        "project_topology_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blueprint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("topology_json", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blueprint_id"], ["project_blueprints.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_topology_snapshots_tenant_id", "project_topology_snapshots", ["tenant_id"])
    op.create_index("ix_project_topology_snapshots_project_id", "project_topology_snapshots", ["project_id"])
    op.create_index("ix_project_topology_snapshots_blueprint_id", "project_topology_snapshots", ["blueprint_id"])
    op.create_index(
        "idx_project_topology_snapshots_project",
        "project_topology_snapshots",
        ["tenant_id", "project_id"],
    )

    op.create_table(
        "project_genesis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blueprint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_task_ids", sa.JSON(), nullable=True),
        sa.Column("validation", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blueprint_id"], ["project_blueprints.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_genesis_runs_tenant_id", "project_genesis_runs", ["tenant_id"])
    op.create_index("ix_project_genesis_runs_project_id", "project_genesis_runs", ["project_id"])
    op.create_index("ix_project_genesis_runs_blueprint_id", "project_genesis_runs", ["blueprint_id"])
    op.create_index("idx_project_genesis_runs_project", "project_genesis_runs", ["tenant_id", "project_id"])


def downgrade() -> None:
    op.drop_index("idx_project_genesis_runs_project", table_name="project_genesis_runs")
    op.drop_index("ix_project_genesis_runs_blueprint_id", table_name="project_genesis_runs")
    op.drop_index("ix_project_genesis_runs_project_id", table_name="project_genesis_runs")
    op.drop_index("ix_project_genesis_runs_tenant_id", table_name="project_genesis_runs")
    op.drop_table("project_genesis_runs")

    op.drop_index("idx_project_topology_snapshots_project", table_name="project_topology_snapshots")
    op.drop_index("ix_project_topology_snapshots_blueprint_id", table_name="project_topology_snapshots")
    op.drop_index("ix_project_topology_snapshots_project_id", table_name="project_topology_snapshots")
    op.drop_index("ix_project_topology_snapshots_tenant_id", table_name="project_topology_snapshots")
    op.drop_table("project_topology_snapshots")

    op.drop_index("idx_project_blueprints_project", table_name="project_blueprints")
    op.drop_index("ix_project_blueprints_project_id", table_name="project_blueprints")
    op.drop_index("ix_project_blueprints_tenant_id", table_name="project_blueprints")
    op.drop_table("project_blueprints")

    op.drop_index("ix_stack_presets_tenant_id", table_name="stack_presets")
    op.drop_table("stack_presets")
