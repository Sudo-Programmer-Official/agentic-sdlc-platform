"""add required_capabilities and agent capabilities list"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260227_0218"
down_revision: Union[str, None] = "20260227_0157"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_items", sa.Column("required_capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.alter_column("work_items", "required_capabilities", server_default=None)
    op.alter_column("agents", "capabilities", type_=sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb"))
    op.alter_column("agents", "capabilities", server_default=None)


def downgrade() -> None:
    op.alter_column("agents", "capabilities", type_=sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb"))
    op.drop_column("work_items", "required_capabilities")
