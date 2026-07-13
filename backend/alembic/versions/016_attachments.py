"""Attachments — user-uploaded files for the Co personal assistant.

Revision ID: 016
Revises: 015
Create Date: 2026-07-12

Changes:
- Add attachments table (uploaded file metadata + parsed text cache).
  Files are uploaded via POST /api/uploads, parsed at upload time
  (ADR-090), and linked to a task at creation (ADR-089). Agents load the
  cached parsed_text into context in AgentBase._load_memory.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("tasks.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("parsed_text", sa.Text, nullable=True),
        sa.Column("parsed_tables", JSONB, nullable=True),
        sa.Column("parse_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("parse_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("attachments")
