"""Static company010 scheduler receipt with native scope and immutable history."""

# ruff: noqa: E501 - static compiled constraint SQL preserves its exact expression.

from alembic import op

revision = "company_010"
down_revision = "company_009"
branch_labels = None
depends_on = None

TABLE_SQL: tuple[str, ...] = (
    """CREATE TABLE company_management_scheduler_scans (
	company_id UUID NOT NULL,
	scan_id UUID NOT NULL,
	consumer VARCHAR(128) NOT NULL,
	recipe_version VARCHAR(128) NOT NULL,
	event_key VARCHAR(128) NOT NULL,
	request_sha256 VARCHAR(64) NOT NULL,
	result_json TEXT NOT NULL,
	owner_id UUID NOT NULL,
	operation_id UUID NOT NULL,
	trace_id UUID NOT NULL,
	start_brain_sequence BIGINT NOT NULL,
	end_brain_sequence BIGINT NOT NULL,
	start_control_sequence BIGINT NOT NULL,
	end_control_sequence BIGINT NOT NULL,
	due_bucket TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (company_id, scan_id),
	CONSTRAINT uq_management_scan_event UNIQUE (company_id, consumer, recipe_version, event_key),
	CONSTRAINT ck_management_scan_sequences CHECK (start_brain_sequence >= 0 AND end_brain_sequence >= start_brain_sequence AND start_control_sequence >= 0 AND end_control_sequence >= start_control_sequence),
	CONSTRAINT ck_management_scan_result CHECK (request_sha256 ~ '^[0-9a-f]{64}$' AND octet_length(result_json) BETWEEN 2 AND 262144),
	FOREIGN KEY(company_id) REFERENCES company_controls (company_id),
	CONSTRAINT fk_management_scan_owner FOREIGN KEY(company_id, owner_id) REFERENCES company_memberships (company_id, principal_id)
)""",
    """CREATE INDEX ix_management_scan_owner ON company_management_scheduler_scans (company_id, owner_id)""",
)


def upgrade() -> None:
    """Install receipt, forced UUID RLS and existing immutable-history guard."""
    for statement in TABLE_SQL:
        op.execute(statement)
    op.execute("ALTER TABLE company_management_scheduler_scans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_management_scheduler_scans FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY company_scope ON company_management_scheduler_scans USING "
        "(company_id = nullif(current_setting('nexus.company_id', true), '')::uuid) "
        "WITH CHECK (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TRIGGER management_immutable BEFORE UPDATE OR DELETE ON company_management_scheduler_scans "
        "FOR EACH ROW EXECUTE FUNCTION nexus_management_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE company_management_scheduler_scans")
