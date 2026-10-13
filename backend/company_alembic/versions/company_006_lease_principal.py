"""Bind lease principal and preserve blocked work across supervised recovery.

Revision ID: company_006
Revises: company_005
Create Date: 2026-10-14

Deployment requires stopped/drained workers before upgrade or rollback. Upgrade
refuses future leases. Old expired leases are invalidated, not given invented
principal ownership. Counters, snapshots, receipts and held totals are retained.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "company_006"
down_revision = "company_005"
branch_labels = None
depends_on = None

_OLD_STATE = "state IN ('eligible','running','awaiting_approval','outcome_unknown','verifying')"
_NEW_STATE = (
    "state IN ('eligible','running','awaiting_approval','outcome_unknown','verifying','blocked')"
)
_OLD_LEASE = (
    "(worker_id IS NULL AND lease_until IS NULL AND lease_mode IS NULL) OR "
    "(worker_id IS NOT NULL AND lease_until IS NOT NULL "
    "AND lease_mode IN ('execute','reconcile'))"
)
_NEW_LEASE = (
    "(worker_id IS NULL AND lease_until IS NULL AND lease_mode IS NULL "
    "AND lease_principal_id IS NULL) OR "
    "(worker_id IS NOT NULL AND lease_until IS NOT NULL AND lease_principal_id IS NOT NULL "
    "AND lease_mode IN ('execute','reconcile'))"
)


def upgrade() -> None:
    """Make ownership explicit only after the operator has drained live leases."""
    _require_operator()
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM company_execution_work
                 WHERE worker_id IS NOT NULL AND lease_until > clock_timestamp()) THEN
        RAISE EXCEPTION 'Drain live execution leases before company_006';
      END IF;
    END; $$;""")
    op.add_column("company_execution_work", sa.Column("lease_principal_id", sa.Uuid()))
    _state_constraint(_NEW_STATE)
    _invalidate_leases()
    _lease_constraint(_NEW_LEASE)
    op.create_foreign_key(
        "fk_company_execution_lease_principal",
        "company_execution_work",
        "company_memberships",
        ["company_id", "lease_principal_id"],
        ["company_id", "principal_id"],
    )


def downgrade() -> None:
    """Fence old callbacks; deactivated blocked work cannot restart under older code."""
    _require_operator()
    _invalidate_leases()
    op.execute("""UPDATE company_registered_work r SET active = false
      FROM company_execution_work w
      WHERE r.company_id = w.company_id AND r.task_id = w.task_id AND w.state = 'blocked'""")
    op.execute("""UPDATE company_execution_work SET state = 'awaiting_approval',
      waiting_action_id = NULL WHERE state = 'blocked'""")
    op.drop_constraint(
        "fk_company_execution_lease_principal",
        "company_execution_work",
        type_="foreignkey",
    )
    _lease_constraint(_OLD_LEASE)
    _state_constraint(_OLD_STATE)
    op.drop_column("company_execution_work", "lease_principal_id")


def _require_operator() -> None:
    """FORCE RLS data migration must never silently skip hidden tenant rows."""
    elevated = op.get_bind().scalar(
        sa.text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
    )
    if not elevated:
        raise RuntimeError("Company lease migration requires its privileged migration operator")


def _state_constraint(expression: str) -> None:
    op.drop_constraint("ck_company_execution_state", "company_execution_work", type_="check")
    op.create_check_constraint("ck_company_execution_state", "company_execution_work", expression)


def _lease_constraint(expression: str) -> None:
    op.drop_constraint("ck_company_execution_lease", "company_execution_work", type_="check")
    op.create_check_constraint("ck_company_execution_lease", "company_execution_work", expression)


def _invalidate_leases() -> None:
    """No inferred refund or counter reset when an old process loses ownership."""
    op.execute("""UPDATE company_cost_holds h SET state = 'unknown'
      FROM company_effect_intents e, company_execution_work w
      WHERE h.company_id = e.company_id AND h.action_id = e.action_id
        AND e.company_id = w.company_id AND e.task_id = w.task_id
        AND w.worker_id IS NOT NULL AND e.state = 'intent' AND h.state = 'held'""")
    op.execute("""UPDATE company_effect_intents e SET state = 'outcome_unknown'
      FROM company_execution_work w
      WHERE e.company_id = w.company_id AND e.task_id = w.task_id
        AND w.worker_id IS NOT NULL AND e.state = 'intent'""")
    op.execute("""UPDATE company_execution_work w SET
      state = CASE WHEN EXISTS (SELECT 1 FROM company_effect_intents e
        WHERE e.company_id = w.company_id AND e.task_id = w.task_id
          AND e.state = 'outcome_unknown') THEN 'outcome_unknown'
        WHEN w.state = 'running' THEN 'blocked' ELSE w.state END,
      fence = fence + 1, worker_id = NULL, lease_until = NULL, lease_mode = NULL,
      lease_principal_id = NULL WHERE worker_id IS NOT NULL""")
