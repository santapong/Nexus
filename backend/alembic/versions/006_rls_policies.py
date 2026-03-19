"""Row-Level Security policies for multi-tenant workspace isolation.

Enables PostgreSQL RLS on all workspace-scoped tables. Each query is
automatically filtered by `nexus.workspace_id` set via `SET LOCAL` at
the start of every database session.

Tables with RLS:
- agents, tasks, episodic_memory, semantic_memory, llm_usage
- audit_log, human_approvals, a2a_tokens, billing_records
- agent_listings, marketplace_reviews, workspaces, workspace_members

Also adds: oauth_accounts table, webhook_subscriptions table,
task_schedules table, audit_log date partitioning prep columns.

Revision ID: 006
Revises: 005
Create Date: 2026-03-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that have workspace_id column and need RLS
_WORKSPACE_TABLES = [
    "agents",
    "tasks",
    "a2a_tokens",
    "billing_records",
    "agent_listings",
    "marketplace_reviews",
    "workspaces",
    "workspace_members",
]

# Tables that reference workspace indirectly via agent_id → agents.workspace_id
# These get RLS via a join-based policy
_AGENT_SCOPED_TABLES = [
    "episodic_memory",
    "semantic_memory",
    "llm_usage",
    "human_approvals",
]


def upgrade() -> None:
    # ── 1. OAuth accounts table ──────────────────────────────────────────
    op.create_table(
        "oauth_accounts",
        sa.Column(
            "id", sa.String(36), primary_key=True,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"),
            nullable=False, index=True,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("access_token_encrypted", sa.Text, nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    # ── 2. Webhook subscriptions table ───────────────────────────────────
    op.create_table(
        "webhook_subscriptions",
        sa.Column(
            "id", sa.String(36), primary_key=True,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column(
            "workspace_id", sa.String(36),
            sa.ForeignKey("workspaces.id"), nullable=False, index=True,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("events", sa.ARRAY(sa.Text), nullable=False),  # task.completed, task.failed, etc.
        sa.Column("secret_hash", sa.String(64), nullable=False),  # HMAC signing secret hash
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("failure_count", sa.Integer, default=0),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── 3. Audit log archival column ─────────────────────────────────────
    op.add_column("audit_log", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_log", sa.Column(
        "workspace_id", sa.String(36), nullable=True,
    ))
    op.create_index("ix_audit_log_workspace", "audit_log", ["workspace_id"])
    op.create_index("ix_audit_log_archived", "audit_log", ["archived_at"],
                     postgresql_where=sa.text("archived_at IS NULL"))

    # ── 4. Enable RLS on workspace-scoped tables ─────────────────────────
    for table in _WORKSPACE_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Policy: rows visible only when workspace_id matches session var
        # OR when session var is 'superuser' (for admin/migration operations)
        op.execute(f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (
                workspace_id::text = current_setting('nexus.workspace_id', true)
                OR current_setting('nexus.workspace_id', true) = 'superuser'
                OR workspace_id IS NULL
            )
        """)

    # ── 5. RLS on agent-scoped tables (via agent_id → agents.workspace_id)
    for table in _AGENT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (
                current_setting('nexus.workspace_id', true) = 'superuser'
                OR agent_id IN (
                    SELECT id::text FROM agents
                    WHERE workspace_id::text = current_setting('nexus.workspace_id', true)
                       OR workspace_id IS NULL
                )
            )
        """)

    # ── 6. RLS on new tables ─────────────────────────────────────────────
    op.execute("ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE webhook_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY webhook_subscriptions_workspace_isolation ON webhook_subscriptions
        USING (
            workspace_id::text = current_setting('nexus.workspace_id', true)
            OR current_setting('nexus.workspace_id', true) = 'superuser'
        )
    """)

    # ── 7. Prompts and prompt_benchmarks — no workspace scope (global) ───
    # These are system-wide resources, no RLS needed.

    # ── 8. Audit log RLS (newly scoped) ──────────────────────────────────
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY audit_log_workspace_isolation ON audit_log
        USING (
            workspace_id::text = current_setting('nexus.workspace_id', true)
            OR current_setting('nexus.workspace_id', true) = 'superuser'
            OR workspace_id IS NULL
        )
    """)


def downgrade() -> None:
    # Drop RLS policies
    all_rls_tables = _WORKSPACE_TABLES + _AGENT_SCOPED_TABLES + [
        "webhook_subscriptions", "audit_log",
    ]
    for table in all_rls_tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop indexes and columns from audit_log
    op.drop_index("ix_audit_log_archived", table_name="audit_log")
    op.drop_index("ix_audit_log_workspace", table_name="audit_log")
    op.drop_column("audit_log", "workspace_id")
    op.drop_column("audit_log", "archived_at")

    # Drop new tables
    op.drop_table("webhook_subscriptions")
    op.drop_table("oauth_accounts")
