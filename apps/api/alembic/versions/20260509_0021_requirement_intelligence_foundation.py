"""requirement intelligence foundation

Revision ID: 20260509_0021
Revises: 20260509_0020
Create Date: 2026-05-09 19:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260509_0021"
down_revision = "20260509_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("requirement_id", sa.String(length=120), nullable=True))
    op.create_index("ix_runs_requirement_id", "runs", ["requirement_id"], unique=False)

    op.add_column("artifacts", sa.Column("requirement_id", sa.String(length=120), nullable=True))
    op.create_index("ix_artifacts_requirement_id", "artifacts", ["requirement_id"], unique=False)

    op.add_column("improvement_requests", sa.Column("source_requirement_id", sa.String(length=120), nullable=True))
    op.add_column("improvement_requests", sa.Column("resulting_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("improvement_requests", sa.Column("resulting_pr_url", sa.Text(), nullable=True))
    op.add_column("improvement_requests", sa.Column("resolution_status", sa.String(length=16), nullable=True))
    op.add_column("improvement_requests", sa.Column("resolution_summary", sa.Text(), nullable=True))
    op.create_index(
        "ix_improvement_requests_source_requirement_id",
        "improvement_requests",
        ["source_requirement_id"],
        unique=False,
    )

    op.create_table(
        "requirement_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_id", sa.String(length=120), nullable=False),
        sa.Column("compact_summary", sa.Text(), nullable=True),
        sa.Column("historical_patterns", sa.JSON(), nullable=False),
        sa.Column("prior_successful_fixes", sa.JSON(), nullable=False),
        sa.Column("recurring_failures", sa.JSON(), nullable=False),
        sa.Column("architectural_constraints", sa.JSON(), nullable=False),
        sa.Column("validation_patterns", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_requirement_memories_project_req",
        "requirement_memories",
        ["project_id", "requirement_id"],
        unique=False,
    )

    op.create_table(
        "requirement_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_requirement_id", sa.String(length=120), nullable=False),
        sa.Column("to_requirement_id", sa.String(length=120), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_requirement_relationships_project_from",
        "requirement_relationships",
        ["project_id", "from_requirement_id"],
        unique=False,
    )
    op.create_index(
        "idx_requirement_relationships_project_to",
        "requirement_relationships",
        ["project_id", "to_requirement_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_requirement_relationships_project_to", table_name="requirement_relationships")
    op.drop_index("idx_requirement_relationships_project_from", table_name="requirement_relationships")
    op.drop_table("requirement_relationships")

    op.drop_index("idx_requirement_memories_project_req", table_name="requirement_memories")
    op.drop_table("requirement_memories")

    op.drop_index("ix_improvement_requests_source_requirement_id", table_name="improvement_requests")
    op.drop_column("improvement_requests", "resolution_summary")
    op.drop_column("improvement_requests", "resolution_status")
    op.drop_column("improvement_requests", "resulting_pr_url")
    op.drop_column("improvement_requests", "resulting_run_id")
    op.drop_column("improvement_requests", "source_requirement_id")

    op.drop_index("ix_artifacts_requirement_id", table_name="artifacts")
    op.drop_column("artifacts", "requirement_id")

    op.drop_index("ix_runs_requirement_id", table_name="runs")
    op.drop_column("runs", "requirement_id")
