"""order: remember the unshipped-physical-order reminder

Revision ID: b9d1f3a5c7e9
Revises: a8c0e2f4b6d8
Create Date: 2026-10-11 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d1f3a5c7e9"
down_revision: str | None = "a8c0e2f4b6d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("ship_reminded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("ship_reminded_at")
