"""Static additive013 native metric observation provenance and exact selected goal/plan binding."""

# ruff: noqa: E501 - frozen SQL preserves complete native check/FK expressions.

from alembic import op

revision = "company_013"
down_revision = "company_012"
branch_labels = None
depends_on = None

TABLE = "company_management_metric_observations"
TABLE_SQL: tuple[str, ...] = (
    "CREATE TABLE company_management_metric_observations (\n\tcompany_id UUID NOT NULL, \n\tobservation_id UUID NOT NULL, \n\tgoal_id UUID NOT NULL, \n\tgoal_revision_id UUID NOT NULL, \n\tplan_id UUID NOT NULL, \n\tplan_revision_id UUID NOT NULL, \n\tmetric_id VARCHAR(128) NOT NULL, \n\trecipe VARCHAR(128), \n\tselection_count INTEGER NOT NULL, \n\tvalue_kind VARCHAR(16) NOT NULL, \n\tcount_value INTEGER, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tsnapshot_sha256 VARCHAR(64) NOT NULL, \n\trecord_sha256 VARCHAR(64) NOT NULL, \n\trequest_json TEXT NOT NULL, \n\trecord_json TEXT NOT NULL, \n\trecorded_by UUID NOT NULL, \n\toperation_id UUID NOT NULL, \n\taudit_trace_id UUID NOT NULL, \n\tobserved_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tPRIMARY KEY (company_id, observation_id), \n\tCONSTRAINT uq_management_metric_operation UNIQUE (company_id, operation_id), \n\tCONSTRAINT ck_management_metric_value CHECK (selection_count BETWEEN 1 AND 100 AND ((value_kind = 'known' AND count_value IS NOT NULL AND count_value BETWEEN 0 AND selection_count) OR (value_kind = 'unknown' AND count_value IS NULL))), \n\tCONSTRAINT ck_management_metric_shape CHECK (request_sha256 ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$' AND length(record_json) <= 4194304), \n\tFOREIGN KEY(company_id) REFERENCES company_controls (company_id), \n\tCONSTRAINT fk_management_metric_goal FOREIGN KEY(company_id, goal_id, goal_revision_id) REFERENCES company_management_goal_revisions (company_id, goal_id, revision_id), \n\tCONSTRAINT fk_management_metric_plan FOREIGN KEY(company_id, plan_id, plan_revision_id, goal_id, goal_revision_id) REFERENCES company_management_plan_revisions (company_id, plan_id, plan_revision_id, goal_id, goal_revision_id), \n\tCONSTRAINT fk_management_metric_owner FOREIGN KEY(company_id, recorded_by) REFERENCES company_memberships (company_id, principal_id)\n)",
    "CREATE INDEX ix_management_metric_goal ON company_management_metric_observations (company_id, goal_id, metric_id, observed_at, observation_id)",
    "CREATE INDEX ix_management_metric_plan ON company_management_metric_observations (company_id, plan_id, plan_revision_id, goal_id, goal_revision_id)",
    "CREATE INDEX ix_management_metric_goal_ref ON company_management_metric_observations (company_id, goal_id, goal_revision_id)",
    "CREATE INDEX ix_management_metric_owner ON company_management_metric_observations (company_id, recorded_by)",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE company_management_plan_revisions ADD CONSTRAINT uq_management_plan_metric_scope UNIQUE (company_id, plan_id, plan_revision_id, goal_id, goal_revision_id)"
    )
    for statement in TABLE_SQL:
        op.execute(statement)
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY company_scope ON {TABLE} USING (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid) WITH CHECK (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE TRIGGER management_immutable BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION nexus_management_immutable()"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {TABLE}")
    op.execute(
        "ALTER TABLE company_management_plan_revisions DROP CONSTRAINT uq_management_plan_metric_scope"
    )
