"""llm providers

Revision ID: 7c1a4f2b9d30
Revises: 49ecfccc3133
Create Date: 2026-10-09 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1a4f2b9d30"
down_revision: str | None = "49ecfccc3133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=256), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("model_vision", sa.String(length=128), nullable=False),
        sa.Column("model_chat", sa.String(length=128), nullable=False),
        sa.Column("model_fast", sa.String(length=128), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("anthropic_fallbacks", sa.Boolean(), nullable=False),
        sa.Column("daily_token_budget", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_providers")),
        sa.UniqueConstraint("name", name=op.f("uq_llm_providers_name")),
    )
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_llm_providers_is_active"), ["is_active"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_llm_providers_is_active"))

    op.drop_table("llm_providers")
