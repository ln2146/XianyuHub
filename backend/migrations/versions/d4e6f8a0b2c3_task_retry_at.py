"""monitor task backoff retry instead of pausing on risk control

Revision ID: d4e6f8a0b2c3
Revises: c3d5e7f9a1b2
Create Date: 2026-10-10 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a0b2c3"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("buyer_tasks") as batch:
        batch.add_column(sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True))
    # 风控不再暂停任务：之前因风控被暂停的任务恢复为正常调度
    op.execute("UPDATE buyer_tasks SET paused_reason = NULL WHERE last_status = 'risk' AND paused_reason IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("buyer_tasks") as batch:
        batch.drop_column("retry_at")
