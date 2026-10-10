"""publish draft item location

Revision ID: e5f7a9b1c3d4
Revises: f6a7b8c9d0e1
Create Date: 2026-10-10 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a9b1c3d4"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_drafts") as batch:
        batch.add_column(sa.Column("location", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("publish_drafts") as batch:
        batch.drop_column("location")
