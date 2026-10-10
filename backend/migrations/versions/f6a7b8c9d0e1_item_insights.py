"""item insights persistence table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-10 15:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item_insights",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("ai_data", sa.JSON(), nullable=False),
        sa.Column("item_analysis", sa.JSON(), nullable=True),
        sa.Column("seller_analysis", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("item_id"),
    )


def downgrade() -> None:
    op.drop_table("item_insights")
