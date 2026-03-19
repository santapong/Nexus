"""Phase 5 Track B/C — scheduled tasks, model benchmarks, provider health, cost alerts.

Revision ID: 007
Revises: 006
Create Date: 2026-03-19

New tables:
- task_schedules: cron-based recurring task definitions
- model_benchmarks: quality/cost/speed comparison per model per role
- provider_health: rolling window latency and error rate tracking
- agent_cost_alerts: per-agent daily budget limits with alert thresholds

Schema changes:
- tasks: add schedule_id FK for scheduled task tracking
- tasks: add rework_round column for QA multi-round rework
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── task_schedules ──────────────────────────────────────────────────
    op.create_table(
        "task_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("instruction", sa.Text, nullable=False),
        sa.Column("target_role", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("timezone", sa.String(50), server_default=sa.text("'UTC'")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_runs", sa.Integer, server_default=sa.text("0")),
        sa.Column("max_runs", sa.Integer, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_task_schedules_workspace_id", "task_schedules", ["workspace_id"])
    op.create_index("ix_task_schedules_is_active", "task_schedules", ["is_active"])
    op.create_index("ix_task_schedules_next_run_at", "task_schedules", ["next_run_at"])

    # ─── model_benchmarks ────────────────────────────────────────────────
    op.create_table(
        "model_benchmarks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_role", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("benchmark_id", sa.String(36), sa.ForeignKey("prompt_benchmarks.id"), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("output_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_model_benchmarks_role", "model_benchmarks", ["agent_role"])
    op.create_index("ix_model_benchmarks_model", "model_benchmarks", ["model_name"])

    # ─── provider_health ─────────────────────────────────────────────────
    op.create_table(
        "provider_health",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_p50_ms", sa.Integer, server_default=sa.text("0")),
        sa.Column("latency_p99_ms", sa.Integer, server_default=sa.text("0")),
        sa.Column("error_rate", sa.Float, server_default=sa.text("0.0")),
        sa.Column("total_requests", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_errors", sa.Integer, server_default=sa.text("0")),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_provider_health_provider", "provider_health", ["provider"])

    # ─── agent_cost_alerts ───────────────────────────────────────────────
    op.create_table(
        "agent_cost_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("daily_limit_usd", sa.Float, nullable=False),
        sa.Column("alert_threshold_pct", sa.Float, server_default=sa.text("0.9")),
        sa.Column("webhook_url", sa.String(2048), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_cost_alerts_agent_id", "agent_cost_alerts", ["agent_id"])

    # ─── tasks: add schedule_id + rework_round ───────────────────────────
    op.add_column(
        "tasks",
        sa.Column("schedule_id", sa.String(36), sa.ForeignKey("task_schedules.id"), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("rework_round", sa.Integer, server_default=sa.text("0")),
    )
    op.create_index("ix_tasks_schedule_id", "tasks", ["schedule_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_schedule_id", table_name="tasks")
    op.drop_column("tasks", "rework_round")
    op.drop_column("tasks", "schedule_id")

    op.drop_index("ix_agent_cost_alerts_agent_id", table_name="agent_cost_alerts")
    op.drop_table("agent_cost_alerts")

    op.drop_index("ix_provider_health_provider", table_name="provider_health")
    op.drop_table("provider_health")

    op.drop_index("ix_model_benchmarks_model", table_name="model_benchmarks")
    op.drop_index("ix_model_benchmarks_role", table_name="model_benchmarks")
    op.drop_table("model_benchmarks")

    op.drop_index("ix_task_schedules_next_run_at", table_name="task_schedules")
    op.drop_index("ix_task_schedules_is_active", table_name="task_schedules")
    op.drop_index("ix_task_schedules_workspace_id", table_name="task_schedules")
    op.drop_table("task_schedules")
