"""knowledge doc can belong to one item

Revision ID: d2f4a6b8c0e1
Revises: c1e3f5a7d9b4
Create Date: 2026-10-12 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4a6b8c0e1"
down_revision: str | None = "c1e3f5a7d9b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_docs") as batch:
        batch.add_column(sa.Column("item_id", sa.String(length=32), nullable=True))
        batch.create_index("ix_knowledge_docs_item_id", ["item_id"])


def downgrade() -> None:
    with op.batch_alter_table("knowledge_docs") as batch:
        batch.drop_index("ix_knowledge_docs_item_id")
        batch.drop_column("item_id")
