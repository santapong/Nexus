"""Phase 5 remaining — RLHF feedback signals, fine-tuning jobs, plugin registrations.

Revision ID: 008
Revises: 007
Create Date: 2026-03-19

New tables:
- feedback_signals: RLHF-lite human feedback capture (Track B)
- fine_tuning_jobs: Ollama fine-tuning job tracking (Track B)
- plugin_registrations: Custom MCP tool plugin registry (Track C)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── feedback_signals (RLHF-lite) ──────────────────────────────────
    op.create_table(
        "feedback_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("signal_value", sa.Float, nullable=False),
        sa.Column("context", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_feedback_signals_task_id", "feedback_signals", ["task_id"])
    op.create_index("ix_feedback_signals_agent_id", "feedback_signals", ["agent_id"])
    op.create_index("ix_feedback_signals_signal_type", "feedback_signals", ["signal_type"])
    op.create_index("ix_feedback_signals_created_at", "feedback_signals", ["created_at"])

    # ── fine_tuning_jobs ──────────────────────────────────────────────
    op.create_table(
        "fine_tuning_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("agent_role", sa.String(50), nullable=False),
        sa.Column("base_model", sa.String(100), nullable=False),
        sa.Column("target_model", sa.String(100), nullable=False),
        sa.Column("dataset_path", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_fine_tuning_jobs_agent_id", "fine_tuning_jobs", ["agent_id"])
    op.create_index("ix_fine_tuning_jobs_status", "fine_tuning_jobs", ["status"])

    # ── plugin_registrations ──────────────────────────────────────────
    op.create_table(
        "plugin_registrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plugin_id", sa.String(500), nullable=False, unique=True),
        sa.Column("plugin_type", sa.String(20), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("manifest", JSONB, nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_plugin_registrations_plugin_id", "plugin_registrations", ["plugin_id"])
    op.create_index("ix_plugin_registrations_workspace_id", "plugin_registrations", ["workspace_id"])
    op.create_index("ix_plugin_registrations_is_active", "plugin_registrations", ["is_active"])


def downgrade() -> None:
    op.drop_table("plugin_registrations")
    op.drop_table("fine_tuning_jobs")
    op.drop_table("feedback_signals")
