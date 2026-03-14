"""add ai routing control tables

Revision ID: 20260314_0009
Revises: 20260314_0008
Create Date: 2026-03-14 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260314_0009"
down_revision: Union[str, None] = "20260314_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_job_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("knowledge_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_type", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("ambiguity_level", sa.String(length=16), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("max_model_tier", sa.String(length=24), nullable=False),
        sa.Column("selected_model_tier", sa.String(length=24), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_context_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_cents", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_cents", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_cost_cents", sa.Float(), nullable=False, server_default="0"),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approval_state", sa.String(length=16), nullable=False, server_default="not_required"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_kind", sa.String(length=64), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["knowledge_event_id"], ["knowledge_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["repository_id"], ["project_repositories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ai_job_runs_project_created", "ai_job_runs", ["project_id", "created_at"], unique=False)
    op.create_index("idx_ai_job_runs_repo_created", "ai_job_runs", ["repository_id", "created_at"], unique=False)
    op.create_index(
        "idx_ai_job_runs_workflow_created",
        "ai_job_runs",
        ["workflow_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_ai_job_runs_tier_created",
        "ai_job_runs",
        ["selected_model_tier", "created_at"],
        unique=False,
    )
    op.create_index("idx_ai_job_runs_status_created", "ai_job_runs", ["status", "created_at"], unique=False)

    op.create_table(
        "ai_artifact_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cache_scope", sa.String(length=64), nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("source_revision", sa.String(length=128), nullable=False, server_default="global"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["repository_id"], ["project_repositories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "repository_id",
            "cache_scope",
            "cache_key",
            "source_revision",
            name="uq_ai_artifact_cache_scope_key_revision",
        ),
    )
    op.create_index(
        "idx_ai_artifact_cache_project_scope",
        "ai_artifact_cache",
        ["project_id", "cache_scope", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_ai_artifact_cache_repo_scope",
        "ai_artifact_cache",
        ["repository_id", "cache_scope", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ai_artifact_cache_repo_scope", table_name="ai_artifact_cache")
    op.drop_index("idx_ai_artifact_cache_project_scope", table_name="ai_artifact_cache")
    op.drop_table("ai_artifact_cache")
    op.drop_index("idx_ai_job_runs_status_created", table_name="ai_job_runs")
    op.drop_index("idx_ai_job_runs_tier_created", table_name="ai_job_runs")
    op.drop_index("idx_ai_job_runs_workflow_created", table_name="ai_job_runs")
    op.drop_index("idx_ai_job_runs_repo_created", table_name="ai_job_runs")
    op.drop_index("idx_ai_job_runs_project_created", table_name="ai_job_runs")
    op.drop_table("ai_job_runs")
