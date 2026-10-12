"""Track verified platform payment event time without trusting legacy inferred times."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1e3f5a7d9b4"
down_revision: str | None = "b0d2f4a6c8e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("actual_paid_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_orders_actual_paid_at", ["actual_paid_at"])


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_actual_paid_at")
        batch.drop_column("actual_paid_at")
