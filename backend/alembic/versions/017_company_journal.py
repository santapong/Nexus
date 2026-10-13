"""Add the standalone company approval and spend journal (ADR-100).

Revision ID: 017
Revises: 016
Create Date: 2026-10-13

New intake remains disabled until API/DBOS/authentication cutover gates pass.
No legacy table is changed or dropped. The journal uses a separate RLS context.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create additive ledger tables, row policies and immutable snapshot guard."""
    _controls()
    _actions()
    _budgets()
    _holds()
    _row_policies()
    _snapshot_guard()


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
    for table in (
        "company_cost_holds",
        "company_work_budgets",
        "company_daily_budgets",
        "company_action_journal",
        "company_controls",
    ):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION nexus_company_snapshot_guard()"))
