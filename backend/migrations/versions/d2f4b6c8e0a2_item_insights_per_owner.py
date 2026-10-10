"""item_insights: one record per user (owner_id), not one shared per item

Revision ID: d2f4b6c8e0a2
Revises: c1e3a5b7d9f1
Create Date: 2026-10-11 10:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4b6c8e0a2"
down_revision: str | None = "c1e3a5b7d9f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item_insights_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(32), nullable=False),
        sa.Column("ai_data", sa.JSON(), nullable=False),
        sa.Column("item_analysis", sa.JSON(), nullable=True),
        sa.Column("seller_analysis", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "item_id", name="uq_item_insights_owner_item"),
    )
    # 已有的点评归第一个管理员（之前所有人共用一份）
    op.execute(
        """
        INSERT INTO item_insights_new (owner_id, item_id, ai_data, item_analysis, seller_analysis, created_at, updated_at)
        SELECT (SELECT MIN(id) FROM users WHERE role = 'admin'), item_id, ai_data, item_analysis, seller_analysis,
               created_at, updated_at
        FROM item_insights
        WHERE EXISTS (SELECT 1 FROM users WHERE role = 'admin')
        """
    )
    op.drop_table("item_insights")
    op.rename_table("item_insights_new", "item_insights")
    op.create_index("ix_item_insights_owner_id", "item_insights", ["owner_id"])
    op.create_index("ix_item_insights_item_id", "item_insights", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_item_insights_item_id", "item_insights")
    op.drop_index("ix_item_insights_owner_id", "item_insights")
    op.create_table(
        "item_insights_old",
        sa.Column("item_id", sa.String(32), primary_key=True),
        sa.Column("ai_data", sa.JSON(), nullable=False),
        sa.Column("item_analysis", sa.JSON(), nullable=True),
        sa.Column("seller_analysis", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        """
        INSERT INTO item_insights_old (item_id, ai_data, item_analysis, seller_analysis, created_at, updated_at)
        SELECT item_id, ai_data, item_analysis, seller_analysis, MAX(created_at), MAX(updated_at)
        FROM item_insights GROUP BY item_id
        """
    )
    op.drop_table("item_insights")
    op.rename_table("item_insights_old", "item_insights")
