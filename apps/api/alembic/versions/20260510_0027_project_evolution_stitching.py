"""project evolution stitching fields and indexes

Revision ID: 20260510_0027
Revises: 20260510_0026
Create Date: 2026-05-10 14:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260510_0027"
down_revision = "20260510_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_evolution_events", sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("project_evolution_events", sa.Column("contract_id", sa.String(length=120), nullable=True))
    op.add_column(
        "project_evolution_events",
        sa.Column("retention_class", sa.String(length=16), nullable=False, server_default="keep"),
    )

    op.create_index(
        "idx_project_evolution_events_project_task_event_at",
        "project_evolution_events",
        ["project_id", "task_id", "event_at"],
    )
    op.create_index(
        "idx_project_evolution_events_project_severity_event_at",
        "project_evolution_events",
        ["project_id", "severity", "event_at"],
    )
    op.create_index(
        "idx_project_evolution_events_project_retention_event_at",
        "project_evolution_events",
        ["project_id", "retention_class", "event_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_project_evolution_events_project_retention_event_at", table_name="project_evolution_events")
    op.drop_index("idx_project_evolution_events_project_severity_event_at", table_name="project_evolution_events")
    op.drop_index("idx_project_evolution_events_project_task_event_at", table_name="project_evolution_events")
    op.drop_column("project_evolution_events", "retention_class")
    op.drop_column("project_evolution_events", "contract_id")
    op.drop_column("project_evolution_events", "task_id")
