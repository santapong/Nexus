"""Add eval_results table.

Revision ID: 003
Revises: 002
Create Date: 2026-03-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.Column("completeness", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("formatting", sa.Float(), nullable=True),
        sa.Column("judge_reasoning", sa.Text(), nullable=True),
        sa.Column("judge_model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Advanced Alchemy sentinel column
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_results_task_id", "eval_results", ["task_id"])


def downgrade() -> None:
    op.drop_table("eval_results")
