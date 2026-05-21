"""runtime execution ledger v1

Revision ID: 20260519_0041
Revises: 20260519_0040
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260519_0041"
down_revision = "20260519_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("feature_key", sa.String(length=120), nullable=True),
        sa.Column("capability_key", sa.String(length=120), nullable=True),
        sa.Column("customer_key", sa.String(length=120), nullable=True),
        sa.Column("total_cost_cents", sa.Float(), nullable=False),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False),
        sa.Column("recovery_overhead_pct", sa.Float(), nullable=False),
        sa.Column("preview_failures", sa.Integer(), nullable=False),
        sa.Column("drift_events", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_run_ledger_run_created", "run_ledger", ["run_id", "created_at"])
    op.create_index("idx_run_ledger_project_created", "run_ledger", ["project_id", "created_at"])
    op.create_index("idx_run_ledger_customer_created", "run_ledger", ["customer_key", "created_at"])

    op.create_table(
        "stage_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("recovery_count", sa.Integer(), nullable=False),
        sa.Column("model_tier", sa.String(length=32), nullable=True),
        sa.Column("files_touched", sa.Integer(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False),
        sa.Column("lines_removed", sa.Integer(), nullable=False),
        sa.Column("package_affinity", sa.String(length=120), nullable=True),
        sa.Column("layer_affinity", sa.String(length=64), nullable=True),
        sa.Column("topology_zone", sa.String(length=64), nullable=True),
        sa.Column("architecture_compliance_score", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_stage_ledger_run_stage_created", "stage_ledger", ["run_id", "stage_name", "created_at"])
    op.create_index("idx_stage_ledger_work_item_created", "stage_ledger", ["work_item_id", "created_at"])

    op.create_table(
        "cost_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("feature_key", sa.String(length=120), nullable=True),
        sa.Column("capability_key", sa.String(length=120), nullable=True),
        sa.Column("model_tier", sa.String(length=32), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_cents", sa.Float(), nullable=False),
        sa.Column("wall_clock_ms", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("preview_cost_units", sa.Integer(), nullable=False),
        sa.Column("recovery_amplification_pct", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_cost_ledger_run_stage_created", "cost_ledger", ["run_id", "stage_name", "created_at"])
    op.create_index("idx_cost_ledger_feature_created", "cost_ledger", ["feature_key", "created_at"])

    op.create_table(
        "patch_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("files_touched", sa.Integer(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False),
        sa.Column("lines_removed", sa.Integer(), nullable=False),
        sa.Column("patch_entropy", sa.Float(), nullable=True),
        sa.Column("monolith_risk", sa.Float(), nullable=True),
        sa.Column("drift_risk", sa.Float(), nullable=True),
        sa.Column("package_affinity", sa.String(length=120), nullable=True),
        sa.Column("layer_affinity", sa.String(length=64), nullable=True),
        sa.Column("topology_zone", sa.String(length=64), nullable=True),
        sa.Column("architecture_compliance_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_patch_ledger_run_stage_created", "patch_ledger", ["run_id", "stage_name", "created_at"])
    op.create_index("idx_patch_ledger_risk_created", "patch_ledger", ["risk_score", "created_at"])

    op.create_table(
        "recovery_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage_name", sa.String(length=64), nullable=True),
        sa.Column("failure_type", sa.String(length=64), nullable=True),
        sa.Column("recovery_action", sa.String(length=64), nullable=True),
        sa.Column("replay_count", sa.Integer(), nullable=False),
        sa.Column("convergence_count", sa.Integer(), nullable=False),
        sa.Column("no_progress_retry_count", sa.Integer(), nullable=False),
        sa.Column("recovery_waste_cost_cents", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_recovery_ledger_run_created", "recovery_ledger", ["run_id", "created_at"])
    op.create_index("idx_recovery_ledger_stage_created", "recovery_ledger", ["stage_name", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_recovery_ledger_stage_created", table_name="recovery_ledger")
    op.drop_index("idx_recovery_ledger_run_created", table_name="recovery_ledger")
    op.drop_table("recovery_ledger")
    op.drop_index("idx_patch_ledger_risk_created", table_name="patch_ledger")
    op.drop_index("idx_patch_ledger_run_stage_created", table_name="patch_ledger")
    op.drop_table("patch_ledger")
    op.drop_index("idx_cost_ledger_feature_created", table_name="cost_ledger")
    op.drop_index("idx_cost_ledger_run_stage_created", table_name="cost_ledger")
    op.drop_table("cost_ledger")
    op.drop_index("idx_stage_ledger_work_item_created", table_name="stage_ledger")
    op.drop_index("idx_stage_ledger_run_stage_created", table_name="stage_ledger")
    op.drop_table("stage_ledger")
    op.drop_index("idx_run_ledger_customer_created", table_name="run_ledger")
    op.drop_index("idx_run_ledger_project_created", table_name="run_ledger")
    op.drop_index("idx_run_ledger_run_created", table_name="run_ledger")
    op.drop_table("run_ledger")
