"""reply rules: hand-off action and images; card pools: images

Revision ID: e3a5c7e9b1d4
Revises: d2f4b6c8e0a2
Create Date: 2026-10-12 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a5c7e9b1d4"
down_revision: str | None = "d2f4b6c8e0a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("reply_rules") as batch:
        batch.add_column(sa.Column("action", sa.String(8), nullable=False, server_default="reply"))
        batch.add_column(sa.Column("images", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("card_pools") as batch:
        batch.add_column(sa.Column("images", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("card_pools") as batch:
        batch.drop_column("images")
    with op.batch_alter_table("reply_rules") as batch:
        batch.drop_column("images")
        batch.drop_column("action")
