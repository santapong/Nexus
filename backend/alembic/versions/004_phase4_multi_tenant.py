"""Phase 4: Multi-tenant tables, marketplace, billing.

Adds users, workspaces, workspace_members, billing_records,
agent_listings, and marketplace_reviews tables. Adds workspace_id
column to agents, tasks, and a2a_tokens for tenant isolation.

Revision ID: 004
Revises: 003
Create Date: 2026-03-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── Table 13: users ─────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ─── Table 14: workspaces ────────────────────────────────────────
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("settings", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("daily_spend_limit_usd", sa.Float(), server_default=sa.text("5.0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    # ─── Table 15: workspace_members ─────────────────────────────────
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), server_default=sa.text("'member'"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    # ─── Table 16: billing_records ───────────────────────────────────
    op.create_table(
        "billing_records",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("billing_type", sa.String(50), nullable=False),
        sa.Column("source_workspace_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_records_workspace_id", "billing_records", ["workspace_id"])
    op.create_index("ix_billing_records_task_id", "billing_records", ["task_id"])
    op.create_index("ix_billing_records_created_at", "billing_records", ["created_at"])

    # ─── Table 17: agent_listings ────────────────────────────────────
    op.create_table(
        "agent_listings",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("skills", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("ARRAY[]::text[]")),
        sa.Column("price_per_task_usd", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rating", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("total_reviews", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_tasks_completed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_listings_workspace_id", "agent_listings", ["workspace_id"])

    # ─── Table 18: marketplace_reviews ───────────────────────────────
    op.create_table(
        "marketplace_reviews",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("listing_id", sa.Uuid(), sa.ForeignKey("agent_listings.id"), nullable=False),
        sa.Column("reviewer_workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_reviews_listing_id", "marketplace_reviews", ["listing_id"])

    # ─── Add workspace_id to existing tables ─────────────────────────
    op.add_column("agents", sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=True))
    op.create_index("ix_agents_workspace_id", "agents", ["workspace_id"])

    op.add_column("tasks", sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=True))
    op.create_index("ix_tasks_workspace_id", "tasks", ["workspace_id"])

    op.add_column("a2a_tokens", sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=True))
    op.create_index("ix_a2a_tokens_workspace_id", "a2a_tokens", ["workspace_id"])


def downgrade() -> None:
    # Drop workspace_id from existing tables
    op.drop_index("ix_a2a_tokens_workspace_id")
    op.drop_column("a2a_tokens", "workspace_id")

    op.drop_index("ix_tasks_workspace_id")
    op.drop_column("tasks", "workspace_id")

    op.drop_index("ix_agents_workspace_id")
    op.drop_column("agents", "workspace_id")

    # Drop new tables (reverse order)
    op.drop_table("marketplace_reviews")
    op.drop_table("agent_listings")
    op.drop_table("billing_records")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
