"""Static additive012 artifact input lineage and explicit generated-output classification."""

# ruff: noqa: E501 - frozen SQL retains exact native FK/check expressions.

from alembic import op

revision = "company_012"
down_revision = "company_011"
branch_labels = None
depends_on = None

TABLE_SQL: tuple[str, ...] = (
    """CREATE TABLE company_brain_artifact_inputs (
	company_id UUID NOT NULL,
	artifact_revision_id UUID NOT NULL,
	input_artifact_revision_id UUID NOT NULL,
	PRIMARY KEY (company_id, artifact_revision_id, input_artifact_revision_id),
	CONSTRAINT ck_brain_artifact_input_distinct CHECK (artifact_revision_id <> input_artifact_revision_id),
	FOREIGN KEY(company_id) REFERENCES company_controls (company_id),
	CONSTRAINT fk_company_brain_artifact_inputs_output FOREIGN KEY(company_id, artifact_revision_id) REFERENCES company_brain_artifact_revisions (company_id, artifact_revision_id),
	CONSTRAINT fk_brain_artifact_input_parent FOREIGN KEY(company_id, input_artifact_revision_id) REFERENCES company_brain_artifact_revisions (company_id, artifact_revision_id)
)""",
    """CREATE INDEX ix_brain_artifact_input_parent ON company_brain_artifact_inputs (company_id, input_artifact_revision_id)""",
    """CREATE TABLE company_brain_artifact_resource_inputs (
	company_id UUID NOT NULL,
	artifact_revision_id UUID NOT NULL,
	resource_id UUID NOT NULL,
	PRIMARY KEY (company_id, artifact_revision_id, resource_id),
	FOREIGN KEY(company_id) REFERENCES company_controls (company_id),
	CONSTRAINT fk_company_brain_artifact_resource_inputs_output FOREIGN KEY(company_id, artifact_revision_id) REFERENCES company_brain_artifact_revisions (company_id, artifact_revision_id),
	CONSTRAINT fk_brain_artifact_resource_input FOREIGN KEY(company_id, resource_id) REFERENCES company_brain_resources (company_id, resource_id)
)""",
    """CREATE INDEX ix_brain_artifact_resource_input ON company_brain_artifact_resource_inputs (company_id, resource_id)""",
)

TABLES = ("company_brain_artifact_inputs", "company_brain_artifact_resource_inputs")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE company_brain_artifact_revisions ADD COLUMN data_classification VARCHAR(16) NULL"
    )
    op.execute(
        "ALTER TABLE company_brain_artifact_revisions ADD CONSTRAINT ck_brain_artifact_classification CHECK (data_classification IS NULL OR data_classification IN ('public','internal','confidential','restricted'))"
    )
    for statement in TABLE_SQL:
        op.execute(statement)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY company_scope ON {table} USING (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid) WITH CHECK (company_id = nullif(current_setting('nexus.company_id', true), '')::uuid)"
        )
        op.execute(
            f"CREATE TRIGGER brain_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION nexus_brain_immutable()"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute(
        "ALTER TABLE company_brain_artifact_revisions DROP CONSTRAINT ck_brain_artifact_classification"
    )
    op.execute("ALTER TABLE company_brain_artifact_revisions DROP COLUMN data_classification")
