"""add executor column to runs"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260227_0126"
down_revision: Union[str, None] = "20260227_0125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("executor", sa.String(length=32), nullable=False, server_default="dummy"))
    op.alter_column("runs", "executor", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "executor")
