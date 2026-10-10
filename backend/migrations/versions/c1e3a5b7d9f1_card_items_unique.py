"""card_items: unique (pool_id, fingerprint)

Revision ID: c1e3a5b7d9f1
Revises: b9d1f3a5c7e9
Create Date: 2026-10-11 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1e3a5b7d9f1"
down_revision: str | None = "b9d1f3a5c7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 先清理已有重复：多余的「未使用」副本直接删除；已发出 / 锁定的保留记录，改写指纹避免冲突
    op.execute(
        """
        DELETE FROM card_items
        WHERE status = 'available'
          AND id NOT IN (SELECT MIN(id) FROM card_items GROUP BY pool_id, fingerprint)
        """
    )
    op.execute(
        """
        UPDATE card_items
        SET fingerprint = SUBSTR(fingerprint, 1, 40) || '-dup-' || CAST(id AS VARCHAR(20))
        WHERE id NOT IN (SELECT MIN(id) FROM card_items GROUP BY pool_id, fingerprint)
        """
    )
    with op.batch_alter_table("card_items") as batch:
        batch.create_unique_constraint("uq_card_items_pool_fingerprint", ["pool_id", "fingerprint"])


def downgrade() -> None:
    with op.batch_alter_table("card_items") as batch:
        batch.drop_constraint("uq_card_items_pool_fingerprint", type_="unique")
