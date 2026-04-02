"""Workspace storage — persistent versioned file storage for agents.

Revision ID: 011
Revises: 010
Create Date: 2026-04-02

Changes:
- Add workspace_projects table (one row per project, maps to bare git repo)
- Add workspace_files table (file metadata + pgvector embeddings for smart context)
- Add workspace_file_versions table (version history per file)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

# revision identifiers
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── workspace_projects ──────────────────────────────────────────────
    op.create_table(
        "workspace_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("repo_path", sa.String(500), nullable=False),
        sa.Column("default_branch", sa.String(100), nullable=False, server_default="main"),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_workspace_project_slug"),
    )

    # ── workspace_files ─────────────────────────────────────────────────
    op.create_table(
        "workspace_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("workspace_projects.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("is_binary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_commit_sha", sa.String(40), nullable=False),
        sa.Column(
            "last_modified_by_agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column(
            "last_modified_by_task_id",
            sa.String(36),
            sa.ForeignKey("tasks.id"),
            nullable=True,
        ),
        sa.Column("content_summary", sa.Text, nullable=True),
        sa.Column("tags", ARRAY(sa.Text), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Partial unique index: only one active file per (project, path)
    op.create_index(
        "uq_workspace_files_active",
        "workspace_files",
        ["project_id", "file_path"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # GIN index for tag search
    op.create_index(
        "ix_workspace_files_tags",
        "workspace_files",
        ["tags"],
        postgresql_using="gin",
    )

    # IVFFlat index for embedding similarity search
    op.execute(
        "CREATE INDEX ix_workspace_files_embedding "
        "ON workspace_files USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ── workspace_file_versions ─────────────────────────────────────────
    op.create_table(
        "workspace_file_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(36),
            sa.ForeignKey("workspace_files.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("workspace_projects.id"),
            nullable=False,
        ),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("diff_summary", sa.Text, nullable=True),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("tasks.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("commit_message", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_file_versions")
    op.execute("DROP INDEX IF EXISTS ix_workspace_files_embedding")
    op.drop_index("ix_workspace_files_tags", table_name="workspace_files")
    op.drop_index("uq_workspace_files_active", table_name="workspace_files")
    op.drop_table("workspace_files")
    op.drop_table("workspace_projects")
