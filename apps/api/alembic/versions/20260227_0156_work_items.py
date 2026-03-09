"""add work items and edges tables"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260227_0156"
down_revision: Union[str, None] = "20260227_0126"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="QUEUED"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executor", sa.String(length=32), nullable=False, server_default="dummy"),
        sa.Column("assigned_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("depends_on_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_work_items_run_status_prio", "work_items", ["run_id", "status", "priority"])
    op.create_index("idx_work_items_project_run", "work_items", ["project_id", "run_id"])
    op.create_index("idx_work_items_assigned", "work_items", ["assigned_agent_id"])
    op.create_index("idx_work_items_lease", "work_items", ["lease_expires_at"])

    op.create_table(
        "work_item_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_work_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_work_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("idx_wi_edges_run_to", "work_item_edges", ["run_id", "to_work_item_id"])
    op.create_index("idx_wi_edges_run_from", "work_item_edges", ["run_id", "from_work_item_id"])


def downgrade() -> None:
    op.drop_index("idx_wi_edges_run_from", table_name="work_item_edges")
    op.drop_index("idx_wi_edges_run_to", table_name="work_item_edges")
    op.drop_table("work_item_edges")
    op.drop_index("idx_work_items_lease", table_name="work_items")
    op.drop_index("idx_work_items_assigned", table_name="work_items")
    op.drop_index("idx_work_items_project_run", table_name="work_items")
    op.drop_index("idx_work_items_run_status_prio", table_name="work_items")
    op.drop_table("work_items")
