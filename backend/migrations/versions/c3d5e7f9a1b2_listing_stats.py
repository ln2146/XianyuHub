"""listing stats on my_items

Revision ID: c3d5e7f9a1b2
Revises: a1c91cbbc5d2
Create Date: 2026-10-10 01:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d5e7f9a1b2"
down_revision: str | None = "a1c91cbbc5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("my_items") as batch:
        batch.add_column(sa.Column("browse_cnt", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("publish_time", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("stats_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("my_items") as batch:
        batch.drop_column("stats_at")
        batch.drop_column("publish_time")
        batch.drop_column("browse_cnt")
