"""Persist delivery setup intent and outcome for published drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0d2f4a6c8e3"
down_revision: str | None = "a9c1e3f5b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_drafts") as batch:
        batch.add_column(sa.Column("delivery_setup", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("publish_drafts") as batch:
        batch.drop_column("delivery_setup")
