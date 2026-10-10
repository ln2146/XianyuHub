"""llm tier bindings and custom models

Revision ID: e5f6a7b8c9d0
Revises: d4e6f8a0b2c3
Create Date: 2026-10-10 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e6f8a0b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("custom_models", sa.JSON(), nullable=True))

    op.create_table(
        "llm_tier_bindings",
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tier"),
    )
    with op.batch_alter_table("llm_tier_bindings", schema=None) as batch_op:
        batch_op.create_index("ix_llm_tier_bindings_tier", ["tier"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("llm_tier_bindings", schema=None) as batch_op:
        batch_op.drop_index("ix_llm_tier_bindings_tier")

    op.drop_table("llm_tier_bindings")

    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.drop_column("custom_models")
