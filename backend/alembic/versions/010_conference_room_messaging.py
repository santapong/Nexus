"""Conference room messaging — task plan approval and meeting support.

Revision ID: 010
Revises: 009
Create Date: 2026-03-30

Changes:
- Add awaiting_approval to task status enum
- Add requirements (JSONB) column to tasks table
- Add meeting_transcript (JSONB) column to tasks table
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to tasks table
    op.add_column("tasks", sa.Column("requirements", JSONB, nullable=True))
    op.add_column("tasks", sa.Column("meeting_transcript", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "meeting_transcript")
    op.drop_column("tasks", "requirements")
