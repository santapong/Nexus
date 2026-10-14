"""Permanent native owner cancellation with inherited ancestry; no ledger/state rewrite."""

# ruff: noqa: E501 - static constraint SQL retains the exact reviewed expressions.

from alembic import op

revision = "company_011"
down_revision = "company_010"
branch_labels = None
depends_on = None

TABLE_SQL: tuple[str, ...] = (
    "CREATE TABLE company_management_cancellations (\n\tcompany_id UUID NOT NULL, \n\tcancellation_id UUID NOT NULL, \n\toperation_id UUID NOT NULL, \n\ttask_id UUID NOT NULL, \n\ttrace_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tbinding_json TEXT NOT NULL, \n\tregistration_sha256 VARCHAR(64) NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\towner_id UUID NOT NULL, \n\taudit_trace_id UUID NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tPRIMARY KEY (company_id, cancellation_id), \n\tCONSTRAINT uq_management_cancel_operation UNIQUE (company_id, operation_id), \n\tCONSTRAINT ck_management_cancel_hash CHECK (registration_sha256 ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT ck_management_cancel_shape CHECK (octet_length(binding_json) BETWEEN 2 AND 32768 AND length(trim(reason)) BETWEEN 1 AND 500), \n\tFOREIGN KEY(company_id) REFERENCES company_controls (company_id), \n\tCONSTRAINT fk_management_cancel_run FOREIGN KEY(company_id, task_id, run_id) REFERENCES company_execution_work (company_id, task_id, run_id), \n\tCONSTRAINT fk_management_cancel_work FOREIGN KEY(company_id, task_id) REFERENCES company_registered_work (company_id, task_id), \n\tCONSTRAINT fk_management_cancel_owner FOREIGN KEY(company_id, owner_id) REFERENCES company_memberships (company_id, principal_id)\n)",
    "CREATE INDEX ix_management_cancel_owner ON company_management_cancellations (company_id, owner_id)",
    "CREATE INDEX ix_management_cancel_task ON company_management_cancellations (company_id, task_id, recorded_at)",
)


def upgrade() -> None:
    """Install actual native FKs, forced UUID RLS and immutable cancellation history."""
    for statement in TABLE_SQL:
        op.execute(statement)
    op.execute("ALTER TABLE company_management_cancellations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_management_cancellations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY company_scope ON company_management_cancellations USING (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid) WITH CHECK (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TRIGGER cancellation_immutable BEFORE UPDATE OR DELETE ON company_management_cancellations FOR EACH ROW EXECUTE FUNCTION nexus_management_immutable()"
    )
    op.execute("""CREATE FUNCTION nexus_cancellation_target() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM company_execution_work e WHERE e.company_id=NEW.company_id AND e.task_id=NEW.task_id AND e.trace_id=NEW.trace_id AND e.run_id=NEW.run_id AND e.registration_hash=NEW.registration_sha256
        AND NEW.binding_json::jsonb->>'workspace_id'=e.workspace_id::text
        AND NEW.binding_json::jsonb->>'actor_id'=e.actor_id::text
        AND NEW.binding_json::jsonb->>'workflow_name'=e.workflow_name
        AND NEW.binding_json::jsonb->>'workflow_version'=e.workflow_version
        AND NEW.binding_json::jsonb->>'model_profile'=e.model_profile
        AND NEW.binding_json::jsonb->>'model_registry_version'=e.model_registry_version)
      OR NOT EXISTS (SELECT 1 FROM company_controls c WHERE c.company_id=NEW.company_id AND c.owner_id=NEW.owner_id)
      OR NEW.binding_json::jsonb->>'company_id' IS DISTINCT FROM NEW.company_id::text
      OR NEW.binding_json::jsonb->>'task_id' IS DISTINCT FROM NEW.task_id::text
      OR NEW.binding_json::jsonb->>'trace_id' IS DISTINCT FROM NEW.trace_id::text
      OR NEW.binding_json::jsonb->>'run_id' IS DISTINCT FROM NEW.run_id::text
      THEN RAISE EXCEPTION 'Cancellation requires exact native owner/work/trace/run/hash binding'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER cancellation_exact_target BEFORE INSERT ON company_management_cancellations FOR EACH ROW EXECUTE FUNCTION nexus_cancellation_target()"
    )


def downgrade() -> None:
    """Normal profile downgrade removes this owned history table only."""
    op.execute("DROP TABLE company_management_cancellations")
    op.execute("DROP FUNCTION nexus_cancellation_target()")
