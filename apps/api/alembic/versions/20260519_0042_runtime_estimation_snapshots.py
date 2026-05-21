"""runtime estimation snapshots

Revision ID: 20260519_0042
Revises: 20260519_0041
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260519_0042"
down_revision = "20260519_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "estimation_features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False),
        sa.Column("feature_key", sa.String(length=120), nullable=True),
        sa.Column("capability_key", sa.String(length=120), nullable=True),
        sa.Column("customer_key", sa.String(length=120), nullable=True),
        sa.Column("repository_state", sa.String(length=64), nullable=True),
        sa.Column("executor", sa.String(length=32), nullable=True),
        sa.Column("expected_stage_count", sa.Integer(), nullable=False),
        sa.Column("expected_files_count", sa.Integer(), nullable=False),
        sa.Column("expected_components", sa.Integer(), nullable=False),
        sa.Column("expected_backend_modules", sa.Integer(), nullable=False),
        sa.Column("predicted_risk", sa.String(length=16), nullable=True),
        sa.Column("predicted_cost_min_cents", sa.Float(), nullable=True),
        sa.Column("predicted_cost_max_cents", sa.Float(), nullable=True),
        sa.Column("predicted_duration_min_seconds", sa.Float(), nullable=True),
        sa.Column("predicted_duration_max_seconds", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_estimation_features_project_created", "estimation_features", ["project_id", "created_at"])
    op.create_index("idx_estimation_features_run_created", "estimation_features", ["run_id", "created_at"])
    op.create_index("idx_estimation_features_feature_key", "estimation_features", ["feature_key", "created_at"])
    op.create_index(
        "uq_estimation_features_run_snapshot_type",
        "estimation_features",
        ["run_id", "snapshot_type"],
        unique=True,
    )

    op.create_table(
        "estimation_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False),
        sa.Column("run_status", sa.String(length=16), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("total_cost_cents", sa.Float(), nullable=False),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False),
        sa.Column("recovery_overhead_pct", sa.Float(), nullable=False),
        sa.Column("preview_failures", sa.Integer(), nullable=False),
        sa.Column("drift_events", sa.Integer(), nullable=False),
        sa.Column("run_recovery_events", sa.Integer(), nullable=False),
        sa.Column("run_retries", sa.Integer(), nullable=False),
        sa.Column("architecture_compliance_score", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_estimation_outcomes_project_created", "estimation_outcomes", ["project_id", "created_at"])
    op.create_index("idx_estimation_outcomes_run_created", "estimation_outcomes", ["run_id", "created_at"])
    op.create_index("idx_estimation_outcomes_status_created", "estimation_outcomes", ["run_status", "created_at"])
    op.create_index(
        "uq_estimation_outcomes_run_snapshot_type",
        "estimation_outcomes",
        ["run_id", "snapshot_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_estimation_outcomes_run_snapshot_type", table_name="estimation_outcomes")
    op.drop_index("idx_estimation_outcomes_status_created", table_name="estimation_outcomes")
    op.drop_index("idx_estimation_outcomes_run_created", table_name="estimation_outcomes")
    op.drop_index("idx_estimation_outcomes_project_created", table_name="estimation_outcomes")
    op.drop_table("estimation_outcomes")
    op.drop_index("uq_estimation_features_run_snapshot_type", table_name="estimation_features")
    op.drop_index("idx_estimation_features_feature_key", table_name="estimation_features")
    op.drop_index("idx_estimation_features_run_created", table_name="estimation_features")
    op.drop_index("idx_estimation_features_project_created", table_name="estimation_features")
    op.drop_table("estimation_features")
