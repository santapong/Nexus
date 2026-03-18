"""Performance indexes for Phase 5 readiness.

Adds composite and partial indexes for hot query paths:
- Agent task history, pending approvals, billing queries
- Active task lookups (partial index)
- Per-agent cost analytics, audit queries

Revision ID: 005
Revises: 004
Create Date: 2026-03-18

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite: tasks(assigned_agent_id, created_at DESC)
    # Covers: per-agent task history, analytics performance queries
    op.create_index(
        "ix_tasks_agent_created",
        "tasks",
        ["assigned_agent_id", op.inline_literal("created_at DESC")],
    )

    # Composite: human_approvals(status, requested_at DESC)
    # Covers: pending approvals listing (most common query)
    op.create_index(
        "ix_approvals_status_requested",
        "human_approvals",
        ["status", op.inline_literal("requested_at DESC")],
    )

    # Composite: billing_records(workspace_id, created_at DESC)
    # Covers: tenant billing history queries
    op.create_index(
        "ix_billing_workspace_created",
        "billing_records",
        ["workspace_id", op.inline_literal("created_at DESC")],
    )

    # Partial: tasks WHERE status IN ('queued', 'running', 'paused')
    # Covers: active task lookups (small subset of all tasks)
    op.execute(
        "CREATE INDEX ix_tasks_active ON tasks (status, created_at DESC) "
        "WHERE status IN ('queued', 'running', 'paused')"
    )

    # Composite: llm_usage(agent_id, created_at DESC)
    # Covers: per-agent cost analytics, recent LLM calls
    op.create_index(
        "ix_llm_usage_agent_created",
        "llm_usage",
        ["agent_id", op.inline_literal("created_at DESC")],
    )

    # Composite: audit_log(agent_id, created_at DESC)
    # Covers: per-agent audit queries
    op.create_index(
        "ix_audit_agent_created",
        "audit_log",
        ["agent_id", op.inline_literal("created_at DESC")],
    )

    # Composite: episodic_memory(agent_id, created_at DESC)
    # Covers: agent memory recall queries (already has agent_id index, adds ordering)
    op.create_index(
        "ix_episodic_agent_created",
        "episodic_memory",
        ["agent_id", op.inline_literal("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_episodic_agent_created", table_name="episodic_memory")
    op.drop_index("ix_audit_agent_created", table_name="audit_log")
    op.drop_index("ix_llm_usage_agent_created", table_name="llm_usage")
    op.execute("DROP INDEX IF EXISTS ix_tasks_active")
    op.drop_index("ix_billing_workspace_created", table_name="billing_records")
    op.drop_index("ix_approvals_status_requested", table_name="human_approvals")
    op.drop_index("ix_tasks_agent_created", table_name="tasks")
