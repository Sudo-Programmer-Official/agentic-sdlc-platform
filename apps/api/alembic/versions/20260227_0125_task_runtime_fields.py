"""add runtime fields to tasks"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260227_0125"
down_revision: Union[str, None] = "20260227_0124"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("result_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "result_payload")
    op.drop_column("tasks", "last_error")
    op.drop_column("tasks", "finished_at")
    op.drop_column("tasks", "started_at")
