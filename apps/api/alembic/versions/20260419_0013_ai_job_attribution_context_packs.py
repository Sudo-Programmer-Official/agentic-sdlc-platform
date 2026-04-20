"""add ai job attribution fields

Revision ID: 20260419_0013
Revises: 20260314_0012
Create Date: 2026-04-19 12:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260419_0013"
down_revision: Union[str, None] = "20260314_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_job_runs", sa.Column("feature_key", sa.String(length=120), nullable=True))
    op.add_column("ai_job_runs", sa.Column("surface", sa.String(length=120), nullable=True))
    op.add_column("ai_job_runs", sa.Column("entrypoint", sa.String(length=255), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE ai_job_runs
            SET feature_key = COALESCE(
                NULLIF(details_json -> 'metadata' ->> 'feature_key', ''),
                NULLIF(details_json -> 'metadata' ->> 'work_item_key', ''),
                workflow_type
            )
            WHERE feature_key IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_job_runs
            SET surface = COALESCE(
                NULLIF(details_json -> 'metadata' ->> 'surface', ''),
                NULLIF(details_json -> 'metadata' ->> 'work_item_type', ''),
                workflow_type
            )
            WHERE surface IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_job_runs
            SET entrypoint = CASE
                WHEN workflow_type = 'interactive_planning' THEN 'api.generate_tasks'
                WHEN workflow_type = 'docs_verification' THEN 'knowledge.analyze_event'
                WHEN workflow_type = 'repo_implementation_task' THEN 'runtime.codex_executor'
                WHEN workflow_type = 'pr_review' THEN 'runtime.codex_executor'
                ELSE 'legacy.ai_job'
            END
            WHERE entrypoint IS NULL
            """
        )
    )

    op.create_index("idx_ai_job_runs_feature_created", "ai_job_runs", ["feature_key", "created_at"], unique=False)
    op.create_index("idx_ai_job_runs_surface_created", "ai_job_runs", ["surface", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_ai_job_runs_surface_created", table_name="ai_job_runs")
    op.drop_index("idx_ai_job_runs_feature_created", table_name="ai_job_runs")
    op.drop_column("ai_job_runs", "entrypoint")
    op.drop_column("ai_job_runs", "surface")
    op.drop_column("ai_job_runs", "feature_key")
