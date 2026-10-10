"""card binding: relist the item automatically after it sells out

Revision ID: f7b9c1d3e5a7
Revises: e5f7a9b1c3d4
Create Date: 2026-10-10 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7b9c1d3e5a7"
down_revision: str | None = "e5f7a9b1c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card_bindings") as batch:
        batch.add_column(sa.Column("auto_relist", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("card_bindings") as batch:
        batch.drop_column("auto_relist")
