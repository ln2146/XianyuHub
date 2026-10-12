"""Persist seller confirmation of AI listing facts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c1e3f5b7d2"
down_revision: str | None = "e3a5c7e9b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_drafts") as batch:
        batch.add_column(sa.Column("confirmed_facts", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("publish_drafts") as batch:
        batch.drop_column("confirmed_facts")
