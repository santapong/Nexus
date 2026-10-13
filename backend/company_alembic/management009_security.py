"""Frozen company009 row-security/history guards; no evolving model/application imports."""

import sqlalchemy as sa

from alembic import op

TABLES = (
    "company_management_work_acceptances",
    "company_management_mandate_revisions",
    "company_management_mandate_heads",
    "company_management_charter_heads",
    "company_management_goal_heads",
    "company_management_commitment_heads",
    "company_management_report_snapshots",
    "company_management_acceptance_proofs",
    "company_management_acceptance_invalidations",
    "company_management_charter_revisions",
    "company_management_goal_revisions",
    "company_management_procedures",
    "company_management_goal_evidence",
    "company_management_control_events",
    "company_management_plan_revisions",
    "company_management_plan_heads",
    "company_management_owner_decisions",
    "company_management_plan_tasks",
    "company_management_commitment_revisions",
    "company_management_plan_dependencies",
    "company_management_verification_bindings",
    "company_management_revision_events",
)
MUTABLE = (
    "company_management_mandate_heads",
    "company_management_charter_heads",
    "company_management_goal_heads",
    "company_management_commitment_heads",
    "company_management_plan_heads",
)


def install_security() -> None:
    """Force company isolation and immutable history before the normal009 commit."""
    for table in TABLES:
        for statement in (
            "ALTER TABLE %(table)s ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE %(table)s FORCE ROW LEVEL SECURITY",
            "CREATE POLICY company_scope ON %(table)s USING "
            "(company_id = nullif(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid)",
        ):
            op.execute(sa.schema.DDL(statement, context={"table": table}))
    op.execute("""
        CREATE FUNCTION nexus_management_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Management history is immutable'; END; $$
    """)
    for table in TABLES:
        if table not in MUTABLE:
            op.execute(
                sa.schema.DDL(
                    "CREATE TRIGGER management_immutable BEFORE UPDATE OR DELETE ON %(table)s "
                    "FOR EACH ROW EXECUTE FUNCTION nexus_management_immutable()",
                    context={"table": table},
                )
            )
    _install_head_guards()


def _install_head_guards() -> None:
    """Current pointers may advance; company/goal/department identity never changes."""
    op.execute("""
        CREATE FUNCTION nexus_management_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE old_row jsonb; new_row jsonb; revision_table text; revision_key text;
                old_time timestamptz; new_time timestamptz; old_number integer; new_number integer;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Management current state cannot be deleted';
          END IF;
          old_row := to_jsonb(OLD); new_row := to_jsonb(NEW);
          IF (new_row - ARRAY['current_revision_id','active','state','decision_id','procedure_id'])
             IS DISTINCT FROM
             (old_row - ARRAY['current_revision_id','active','state',
                               'decision_id','procedure_id']) THEN
            RAISE EXCEPTION 'Management current identity is immutable';
          END IF;
          IF TG_TABLE_NAME = 'company_management_plan_heads' THEN
            SELECT revision INTO old_number FROM company_management_plan_revisions
             WHERE company_id=OLD.company_id AND plan_revision_id=OLD.current_revision_id;
            SELECT revision INTO new_number FROM company_management_plan_revisions
             WHERE company_id=NEW.company_id AND plan_revision_id=NEW.current_revision_id;
            IF new_number < old_number OR (OLD.procedure_id IS NOT NULL AND
               NEW.procedure_id IS DISTINCT FROM OLD.procedure_id) THEN
              RAISE EXCEPTION 'Management plan revision/root cannot roll back';
            END IF;
          ELSIF NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
            revision_key := 'revision_id';
            CASE TG_TABLE_NAME
              WHEN 'company_management_mandate_heads' THEN
                revision_table := 'company_management_mandate_revisions';
              WHEN 'company_management_charter_heads' THEN
                revision_table := 'company_management_charter_revisions';
              WHEN 'company_management_goal_heads' THEN
                revision_table := 'company_management_goal_revisions';
              WHEN 'company_management_commitment_heads' THEN
                revision_table := 'company_management_commitment_revisions';
              ELSE RAISE EXCEPTION 'Unknown management current pointer';
            END CASE;
            EXECUTE format('SELECT recorded_at FROM %I WHERE company_id=$1 AND %I=$2',
                           revision_table, revision_key) INTO old_time
              USING OLD.company_id, OLD.current_revision_id;
            EXECUTE format('SELECT recorded_at FROM %I WHERE company_id=$1 AND %I=$2',
                           revision_table, revision_key) INTO new_time
              USING NEW.company_id, NEW.current_revision_id;
            IF new_time < old_time THEN
              RAISE EXCEPTION 'Management current pointer cannot roll back';
            END IF;
          END IF;
          RETURN NEW;
        END; $$
    """)
    for table in MUTABLE:
        op.execute(
            sa.schema.DDL(
                "CREATE TRIGGER management_current BEFORE UPDATE OR DELETE ON %(table)s "
                "FOR EACH ROW EXECUTE FUNCTION nexus_management_head_guard()",
                context={"table": table},
            )
        )


def remove_functions() -> None:
    """Tables/triggers have already been removed by company009 downgrade."""
    op.execute("DROP FUNCTION nexus_management_head_guard()")
    op.execute("DROP FUNCTION nexus_management_immutable()")
