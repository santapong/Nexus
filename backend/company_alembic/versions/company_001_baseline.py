"""Explicit clean company-profile baseline (ADR-101).

Revision ID: company_001
Revises: None
Create Date: 2026-10-13

New intake remains disabled until API/DBOS/authentication cutover gates pass.

Baseline DDL exception: this frozen schema snapshot and its table-definition
helpers exceed ordinary application size limits to keep explicit constraints,
RLS and guards reviewable together. It must not derive DDL from evolving ORM
metadata. Future schema changes use additive revisions, not baseline edits.
No legacy table is changed or dropped. The journal uses a separate RLS context.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "company_001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create additive ledger tables, row policies and immutable snapshot guard."""
    _refuse_conflicts()
    _controls()
    _actions()
    _budgets()
    _holds()
    _row_policies()
    _snapshot_guard()
    _directory_tables()
    _directory_policies()
    _directory_guards()


def _row_policies() -> None:
    """Scope each new table to the transaction's authenticated company setting."""
    # These reviewed names are fixed migration identifiers, never request input.
    for table in (
        "company_controls",
        "company_action_journal",
        "company_daily_budgets",
        "company_work_budgets",
        "company_cost_holds",
    ):
        op.execute(
            sa.schema.DDL(
                "ALTER TABLE %(table)s ENABLE ROW LEVEL SECURITY", context={"table": table}
            )
        )
        op.execute(
            sa.schema.DDL(
                "ALTER TABLE %(table)s FORCE ROW LEVEL SECURITY", context={"table": table}
            )
        )
        op.execute(
            sa.schema.DDL(
                "CREATE POLICY company_scope ON %(table)s USING "
                "(company_id::text = nullif(current_setting('nexus.company_id', true), '')) "
                "WITH CHECK (company_id::text = "
                "nullif(current_setting('nexus.company_id', true), ''))",
                context={"table": table},
            )
        )


def _snapshot_guard() -> None:
    """Keep bound proposal, decision and consumption fields immutable in PostgreSQL."""
    op.execute(
        sa.text("""
        CREATE FUNCTION nexus_company_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.id, NEW.company_id, NEW.task_id, NEW.trace_id, NEW.proposal_json,
              NEW.proposal_hash) IS DISTINCT FROM
             (OLD.id, OLD.company_id, OLD.task_id, OLD.trace_id, OLD.proposal_json,
              OLD.proposal_hash) THEN
            RAISE EXCEPTION 'Company action snapshot is immutable';
          END IF;
          IF OLD.approval_json IS NOT NULL
             AND NEW.approval_json IS DISTINCT FROM OLD.approval_json THEN
            RAISE EXCEPTION 'Company approval decision is immutable';
          END IF;
          IF OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at THEN
            RAISE EXCEPTION 'Consumed company approval cannot be reset';
          END IF;
          RETURN NEW;
        END $$;
    """)
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER company_snapshot_immutable BEFORE UPDATE ON company_action_journal
        FOR EACH ROW EXECUTE FUNCTION nexus_company_snapshot_guard();
    """)
    )


def _controls() -> None:
    op.create_table(
        "company_controls",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(500), nullable=False),
        sa.Column("price_version", sa.String(500), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("daily_cap_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("work_cap_usd", sa.Numeric(18, 6), nullable=False),
        sa.CheckConstraint(
            "daily_cap_usd >= 0 AND daily_cap_usd <= 5 AND work_cap_usd >= 0 "
            "AND work_cap_usd <= daily_cap_usd",
            name="ck_company_caps",
        ),
    )


def _actions() -> None:
    op.create_table(
        "company_action_journal",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("company_controls.company_id"), nullable=False
        ),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_json", sa.Text(), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("approval_json", sa.Text(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("company_id", "id", name="uq_company_action_scope"),
    )
    op.create_index(
        "ix_company_action_journal_company_id", "company_action_journal", ["company_id"]
    )
    op.create_index("ix_company_action_journal_task_id", "company_action_journal", ["task_id"])


def _budgets() -> None:
    op.create_table(
        "company_daily_budgets",
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("company_controls.company_id"), primary_key=True
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("held_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("spent_usd", sa.Numeric(18, 6), nullable=False),
        sa.CheckConstraint("held_usd >= 0 AND spent_usd >= 0", name="ck_daily_totals"),
    )
    op.create_table(
        "company_work_budgets",
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("company_controls.company_id"), primary_key=True
        ),
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("held_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("spent_usd", sa.Numeric(18, 6), nullable=False),
        sa.CheckConstraint("held_usd >= 0 AND spent_usd >= 0", name="ck_work_totals"),
    )


def _holds() -> None:
    op.create_table(
        "company_cost_holds",
        sa.Column("action_id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("actual_usd", sa.Numeric(18, 6), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "action_id"],
            ["company_action_journal.company_id", "company_action_journal.id"],
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "day"], ["company_daily_budgets.company_id", "company_daily_budgets.day"]
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["company_work_budgets.company_id", "company_work_budgets.task_id"],
        ),
        sa.CheckConstraint(
            "amount_usd >= 0 AND (actual_usd IS NULL OR actual_usd >= 0)", name="ck_hold_amounts"
        ),
    )
    op.create_index("ix_company_cost_holds_company_id", "company_cost_holds", ["company_id"])


def downgrade() -> None:
    """Remove only new tables; runtime rollback must first preserve their receipts."""
    op.drop_constraint("fk_company_directory_owner", "company_directory", type_="foreignkey")
    for table in (
        "company_work_principals",
        "company_registered_work",
        "company_memberships",
        "company_directory",
        "company_cost_holds",
        "company_work_budgets",
        "company_daily_budgets",
        "company_action_journal",
        "company_controls",
    ):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION nexus_company_snapshot_guard()"))
    op.execute(sa.text("DROP FUNCTION nexus_company_directory_guard()"))
    op.execute(sa.text("DROP FUNCTION nexus_company_work_guard()"))


def _refuse_conflicts() -> None:
    """Never infer migration completion from pre-existing company tables."""
    tables = sa.inspect(op.get_bind()).get_table_names()
    if any(name.startswith("company_") and name != "company_alembic_version" for name in tables):
        raise RuntimeError(
            "Company tables already exist without a baseline revision; use reviewed import"
        )


def _directory_tables() -> None:
    """Create frozen native-UUID mapping and membership definitions."""
    op.create_table(
        "company_directory",
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("company_controls.company_id"), primary_key=True
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("company_active", sa.Boolean(), nullable=False),
        sa.Column("workspace_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "workspace_id", name="uq_company_directory_workspace_scope"
        ),
    )
    op.create_table(
        "company_memberships",
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("company_directory.company_id"), primary_key=True
        ),
        sa.Column("principal_id", sa.Uuid(), primary_key=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("principal_active", sa.Boolean(), nullable=False),
        sa.Column("membership_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')", name="ck_company_membership_role"
        ),
    )
    op.create_foreign_key(
        "fk_company_directory_owner",
        "company_directory",
        "company_memberships",
        ["company_id", "owner_id"],
        ["company_id", "principal_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    _work_tables()


def _work_tables() -> None:
    """Create immutable identity and partitioned lifetime work allocations."""
    op.create_table(
        "company_registered_work",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("parent_task_id", sa.Uuid(), nullable=True),
        sa.Column("root_task_id", sa.Uuid(), nullable=False),
        sa.Column("allocation_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("delegated_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "workspace_id"],
            ["company_directory.company_id", "company_directory.workspace_id"],
            name="fk_company_work_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "actor_id"],
            ["company_memberships.company_id", "company_memberships.principal_id"],
            name="fk_company_work_actor",
        ),
        sa.UniqueConstraint(
            "company_id", "task_id", "root_task_id", name="uq_company_work_root_scope"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "root_task_id"],
            ["company_registered_work.company_id", "company_registered_work.task_id"],
            name="fk_company_work_root",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "parent_task_id", "root_task_id"],
            [
                "company_registered_work.company_id",
                "company_registered_work.task_id",
                "company_registered_work.root_task_id",
            ],
            name="fk_company_work_parent_root",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "allocation_usd >= 0 AND delegated_usd >= 0 AND delegated_usd <= allocation_usd",
            name="ck_company_work_allocation",
        ),
        sa.CheckConstraint(
            "(parent_task_id IS NULL AND root_task_id = task_id) OR "
            "(parent_task_id IS NOT NULL AND parent_task_id <> task_id "
            "AND root_task_id <> task_id)",
            name="ck_company_work_lineage",
        ),
    )
    op.create_index(
        "ix_company_registered_work_parent_task_id", "company_registered_work", ["parent_task_id"]
    )
    op.create_index(
        "ix_company_registered_work_root_task_id", "company_registered_work", ["root_task_id"]
    )
    op.create_table(
        "company_work_principals",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("principal_id", sa.Uuid(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["company_registered_work.company_id", "company_registered_work.task_id"],
            name="fk_company_work_principal_work",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "principal_id"],
            ["company_memberships.company_id", "company_memberships.principal_id"],
            name="fk_company_work_principal_member",
        ),
    )


def _directory_policies() -> None:
    """Allow signed-identity discovery while requiring company context for writes."""
    for table in (
        "company_directory",
        "company_memberships",
        "company_registered_work",
        "company_work_principals",
    ):
        op.execute(
            sa.schema.DDL(
                "ALTER TABLE %(table)s ENABLE ROW LEVEL SECURITY", context={"table": table}
            )
        )
        op.execute(
            sa.schema.DDL(
                "ALTER TABLE %(table)s FORCE ROW LEVEL SECURITY", context={"table": table}
            )
        )
    op.execute(
        sa.text(
            "CREATE POLICY company_directory_scope ON company_directory USING "
            "(company_id::text = nullif(current_setting('nexus.company_id',true),'') OR "
            "workspace_id::text = nullif(current_setting('nexus.workspace_id',true),'')) "
            "WITH CHECK (company_id::text = nullif(current_setting('nexus.company_id',true),''))"
        )
    )
    op.execute(
        sa.text(
            "CREATE POLICY company_membership_scope ON company_memberships USING "
            "(company_id::text = nullif(current_setting('nexus.company_id',true),'') OR "
            "principal_id::text = nullif(current_setting('nexus.principal_id',true),'')) "
            "WITH CHECK (company_id::text = nullif(current_setting('nexus.company_id',true),''))"
        )
    )
    for table in ("company_registered_work", "company_work_principals"):
        op.execute(
            sa.schema.DDL(
                "CREATE POLICY company_scope ON %(table)s USING "
                "(company_id::text = nullif(current_setting('nexus.company_id',true),'')) "
                "WITH CHECK (company_id::text = "
                "nullif(current_setting('nexus.company_id',true),''))",
                context={"table": table},
            )
        )


def _directory_guards() -> None:
    """Protect persisted owner/mapping/work lineage and non-resetting allocations."""
    op.execute(
        sa.text("""
      CREATE FUNCTION nexus_company_directory_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (NEW.company_id, NEW.workspace_id, NEW.owner_id) IS DISTINCT FROM
           (OLD.company_id, OLD.workspace_id, OLD.owner_id) THEN
          RAISE EXCEPTION 'Company mapping and owner are immutable';
        END IF;
        RETURN NEW;
      END $$;
    """)
    )
    op.execute(
        sa.text("""
      CREATE TRIGGER company_directory_immutable BEFORE UPDATE ON company_directory
      FOR EACH ROW EXECUTE FUNCTION nexus_company_directory_guard()
    """)
    )
    op.execute(
        sa.text("""
      CREATE FUNCTION nexus_company_work_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (NEW.company_id, NEW.task_id, NEW.workspace_id, NEW.trace_id, NEW.actor_id,
            NEW.parent_task_id, NEW.root_task_id, NEW.allocation_usd) IS DISTINCT FROM
           (OLD.company_id, OLD.task_id, OLD.workspace_id, OLD.trace_id, OLD.actor_id,
            OLD.parent_task_id, OLD.root_task_id, OLD.allocation_usd) THEN
          RAISE EXCEPTION 'Registered work identity and allocation are immutable';
        END IF;
        IF NEW.delegated_usd < OLD.delegated_usd THEN
          RAISE EXCEPTION 'Delegated lifetime allowance cannot reset';
        END IF;
        RETURN NEW;
      END $$;
    """)
    )
    op.execute(
        sa.text("""
      CREATE TRIGGER company_work_immutable BEFORE UPDATE ON company_registered_work
      FOR EACH ROW EXECUTE FUNCTION nexus_company_work_guard()
    """)
    )
