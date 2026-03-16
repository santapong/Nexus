"""Add dead_letters and a2a_tokens tables.

Revision ID: 002
Revises: 001
Create Date: 2026-03-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Table 10: dead_letters
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_topic", sa.String(100), nullable=False),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("raw_message", postgresql.JSONB(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # Advanced Alchemy sentinel column
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dead_letters_source_topic", "dead_letters", ["source_topic"])
    op.create_index("ix_dead_letters_task_id", "dead_letters", ["task_id"])
    op.create_index("ix_dead_letters_created_at", "dead_letters", ["created_at"])

    # Table 11: a2a_tokens
    op.create_table(
        "a2a_tokens",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("allowed_skills", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # Advanced Alchemy sentinel column
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_a2a_tokens_hash"),
    )
    op.create_index("ix_a2a_tokens_token_hash", "a2a_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_table("a2a_tokens")
    op.drop_table("dead_letters")
