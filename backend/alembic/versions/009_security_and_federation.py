"""Phase 6 security constraints and federation registry.

Revision ID: 009
Revises: 008
Create Date: 2026-03-21

Changes:
- Add index on tasks(workspace_id, created_at) for tenant-filtered queries
- Add federation_registry table for multi-NEXUS instance discovery
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Index for tenant-filtered task queries
    op.create_index(
        "ix_tasks_workspace_created",
        "tasks",
        ["workspace_id", "created_at"],
        if_not_exists=True,
    )

    # Federation registry table
    op.create_table(
        "federation_registry",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("instance_url", sa.String(500), nullable=False, unique=True),
        sa.Column("instance_name", sa.String(200), nullable=False),
        sa.Column("agent_card", JSONB, nullable=False),
        sa.Column("trust_level", sa.String(20), nullable=False, server_default="untrusted"),
        sa.Column("capabilities", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_index(
        "ix_federation_registry_trust_active",
        "federation_registry",
        ["trust_level", "is_active"],
    )


def downgrade() -> None:
    op.drop_table("federation_registry")
    op.drop_index("ix_tasks_workspace_created", table_name="tasks", if_exists=True)
