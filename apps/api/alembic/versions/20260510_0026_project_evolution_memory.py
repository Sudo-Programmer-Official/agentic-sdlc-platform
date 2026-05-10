"""project evolution memory foundation

Revision ID: 20260510_0026
Revises: 20260510_0025
Create Date: 2026-05-10 12:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260510_0026"
down_revision = "20260510_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_evolution_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="observed"),
        sa.Column("requirement_id", sa.String(length=120), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deployment_ref", sa.String(length=200), nullable=True),
        sa.Column("related_artifact_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("related_file_paths", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_project_evolution_events_project_event_at",
        "project_evolution_events",
        ["project_id", "event_at"],
    )
    op.create_index(
        "idx_project_evolution_events_project_domain_event_at",
        "project_evolution_events",
        ["project_id", "domain", "event_at"],
    )
    op.create_index(
        "idx_project_evolution_events_project_requirement_event_at",
        "project_evolution_events",
        ["project_id", "requirement_id", "event_at"],
    )
    op.create_index(
        "idx_project_evolution_events_project_run_event_at",
        "project_evolution_events",
        ["project_id", "run_id", "event_at"],
    )

    op.create_table(
        "memory_summary_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_type", sa.String(length=32), nullable=False),
        sa.Column("source_entity_type", sa.String(length=32), nullable=False),
        sa.Column("source_entity_id", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("window_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_memory_summary_artifacts_project_type_created",
        "memory_summary_artifacts",
        ["project_id", "summary_type", "created_at"],
    )
    op.create_index(
        "idx_memory_summary_artifacts_source_version",
        "memory_summary_artifacts",
        ["source_entity_type", "source_entity_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_summary_artifacts_source_version", table_name="memory_summary_artifacts")
    op.drop_index("idx_memory_summary_artifacts_project_type_created", table_name="memory_summary_artifacts")
    op.drop_table("memory_summary_artifacts")

    op.drop_index("idx_project_evolution_events_project_run_event_at", table_name="project_evolution_events")
    op.drop_index("idx_project_evolution_events_project_requirement_event_at", table_name="project_evolution_events")
    op.drop_index("idx_project_evolution_events_project_domain_event_at", table_name="project_evolution_events")
    op.drop_index("idx_project_evolution_events_project_event_at", table_name="project_evolution_events")
    op.drop_table("project_evolution_events")
