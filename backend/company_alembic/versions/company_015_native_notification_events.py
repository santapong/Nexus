"""Static additive015 native notification wake selectors; no emitter/transport activation.

Downgrade refuses persisted new-kind evidence before dropping native columns.
"""

# ruff: noqa: E501 - frozen SQL retains complete native FK/NULL guards.
from alembic import op

revision = "company_015"
down_revision = "company_014"
branch_labels = None
depends_on = None

UPGRADE_SQL: tuple[str, ...] = (
    "ALTER TABLE company_action_journal ADD CONSTRAINT uq_company_action_task_scope UNIQUE (company_id,id,task_id)",
    "ALTER TABLE company_brain_events ADD COLUMN task_id UUID, ADD COLUMN report_id UUID, ADD COLUMN budget_day DATE, ADD COLUMN native_snapshot_sha256 VARCHAR(64), ADD COLUMN due_bucket VARCHAR(128), ADD COLUMN scheduled_for TIMESTAMP WITH TIME ZONE, ADD COLUMN notification_policy_sha256 VARCHAR(64)",
    "ALTER TABLE company_brain_events DROP CONSTRAINT ck_brain_event_kind",
    "ALTER TABLE company_brain_events ADD CONSTRAINT ck_brain_event_kind CHECK (kind IN ('source_revised','acl_changed','claims_changed','derivation_changed','receipt_recorded','verification_recorded','decision_required','work_blocked','cap_exhausted','digest_due'))",
    "ALTER TABLE company_brain_events ADD CONSTRAINT ck_brain_event_native_hashes CHECK ((native_snapshot_sha256 IS NULL OR native_snapshot_sha256 ~ '^[0-9a-f]{64}$') AND (notification_policy_sha256 IS NULL OR notification_policy_sha256 ~ '^[0-9a-f]{64}$') AND (due_bucket IS NULL OR length(due_bucket) BETWEEN 1 AND 128))",
    "ALTER TABLE company_brain_events ADD CONSTRAINT ck_brain_event_native_binding CHECK (((kind IN ('source_revised','acl_changed','claims_changed','derivation_changed','receipt_recorded','verification_recorded') AND task_id IS NULL AND report_id IS NULL AND budget_day IS NULL AND native_snapshot_sha256 IS NULL AND due_bucket IS NULL AND scheduled_for IS NULL AND notification_policy_sha256 IS NULL) OR (kind IN ('decision_required','work_blocked','cap_exhausted','digest_due') AND source_revision_id IS NULL AND resource_generation IS NULL AND native_snapshot_sha256 IS NOT NULL AND ((kind = 'decision_required' AND task_id IS NOT NULL AND action_id IS NOT NULL AND report_id IS NULL AND budget_day IS NULL AND due_bucket IS NULL AND scheduled_for IS NULL AND notification_policy_sha256 IS NULL) OR (kind = 'work_blocked' AND task_id IS NOT NULL AND action_id IS NULL AND report_id IS NULL AND budget_day IS NULL AND due_bucket IS NULL AND scheduled_for IS NULL AND notification_policy_sha256 IS NULL) OR (kind = 'cap_exhausted' AND action_id IS NULL AND report_id IS NULL AND ((task_id IS NOT NULL AND budget_day IS NULL) OR (task_id IS NULL AND budget_day IS NOT NULL)) AND due_bucket IS NULL AND scheduled_for IS NULL AND notification_policy_sha256 IS NULL) OR (kind = 'digest_due' AND action_id IS NULL AND task_id IS NULL AND budget_day IS NULL AND report_id IS NOT NULL AND due_bucket IS NOT NULL AND scheduled_for IS NOT NULL AND notification_policy_sha256 IS NOT NULL)))))",
    "ALTER TABLE company_brain_events ADD CONSTRAINT fk_brain_event_native_task FOREIGN KEY (company_id,task_id) REFERENCES company_registered_work (company_id,task_id)",
    "CREATE INDEX ix_brain_event_native_task ON company_brain_events (company_id,task_id)",
    "ALTER TABLE company_brain_events ADD CONSTRAINT fk_brain_event_native_report FOREIGN KEY (company_id,report_id) REFERENCES company_management_report_snapshots (company_id,report_id)",
    "CREATE INDEX ix_brain_event_native_report ON company_brain_events (company_id,report_id)",
    "ALTER TABLE company_brain_events ADD CONSTRAINT fk_brain_event_native_budget FOREIGN KEY (company_id,budget_day) REFERENCES company_daily_budgets (company_id,day)",
    "CREATE INDEX ix_brain_event_native_budget ON company_brain_events (company_id,budget_day)",
    "ALTER TABLE company_brain_events ADD CONSTRAINT fk_brain_event_native_action_task FOREIGN KEY (company_id,action_id,task_id) REFERENCES company_action_journal (company_id,id,task_id)",
    "CREATE INDEX ix_brain_event_native_action_task ON company_brain_events (company_id,action_id,task_id)",
)

DOWNGRADE_SQL: tuple[str, ...] = (
    "ALTER TABLE company_brain_events DROP CONSTRAINT ck_brain_event_kind",
    "ALTER TABLE company_brain_events ADD CONSTRAINT ck_brain_event_kind CHECK (kind IN ('source_revised','acl_changed','claims_changed','derivation_changed','receipt_recorded','verification_recorded'))",
    "ALTER TABLE company_brain_events DROP CONSTRAINT fk_brain_event_native_action_task",
    "DROP INDEX ix_brain_event_native_action_task",
    "ALTER TABLE company_brain_events DROP CONSTRAINT fk_brain_event_native_budget",
    "DROP INDEX ix_brain_event_native_budget",
    "ALTER TABLE company_brain_events DROP CONSTRAINT fk_brain_event_native_report",
    "DROP INDEX ix_brain_event_native_report",
    "ALTER TABLE company_brain_events DROP CONSTRAINT fk_brain_event_native_task",
    "DROP INDEX ix_brain_event_native_task",
    "ALTER TABLE company_brain_events DROP CONSTRAINT ck_brain_event_native_binding",
    "ALTER TABLE company_brain_events DROP CONSTRAINT ck_brain_event_native_hashes",
    "ALTER TABLE company_brain_events DROP COLUMN notification_policy_sha256, DROP COLUMN scheduled_for, DROP COLUMN due_bucket, DROP COLUMN native_snapshot_sha256, DROP COLUMN budget_day, DROP COLUMN report_id, DROP COLUMN task_id",
    "ALTER TABLE company_action_journal DROP CONSTRAINT uq_company_action_task_scope",
)


def upgrade() -> None:
    """Add only immutable selectors and exact native identity constraints."""
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    """Fail transactionally if new-kind rows exist; preserve their durable evidence."""
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
