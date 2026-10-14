"""Additive native event Table metadata without instrumenting the legacy BrainEvent mapper."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Uuid,
)

NATIVE_EVENT_FIELDS = (
    "task_id",
    "report_id",
    "budget_day",
    "native_snapshot_sha256",
    "due_bucket",
    "scheduled_for",
    "notification_policy_sha256",
)
OLD_EVENT_KINDS = (
    "source_revised",
    "acl_changed",
    "claims_changed",
    "derivation_changed",
    "receipt_recorded",
    "verification_recorded",
)
NATIVE_EVENT_KINDS = ("decision_required", "work_blocked", "cap_exhausted", "digest_due")


NATIVE_CHECK_0 = (
    "kind IN "
    "('source_revised','acl_changed','claims_changed','derivation_changed','receipt_recorded','verification_recorded','decision_required','work_blocked','cap_exhausted','digest_due')"
)

NATIVE_CHECK_1 = (
    "(native_snapshot_sha256 IS NULL OR native_snapshot_sha256 ~ '^[0-9a-f]{64}$') AND "
    "(notification_policy_sha256 IS NULL OR notification_policy_sha256 ~ "
    "'^[0-9a-f]{64}$') AND (due_bucket IS NULL OR length(due_bucket) BETWEEN 1 AND 128)"
)

NATIVE_CHECK_2 = (
    "((kind IN "
    "('source_revised','acl_changed','claims_changed','derivation_changed','receipt_recorded','verification_recorded')"
    " AND task_id IS NULL AND report_id IS NULL AND budget_day IS NULL AND "
    "native_snapshot_sha256 IS NULL AND due_bucket IS NULL AND scheduled_for IS NULL AND "
    "notification_policy_sha256 IS NULL) OR (kind IN "
    "('decision_required','work_blocked','cap_exhausted','digest_due') AND "
    "source_revision_id IS NULL AND resource_generation IS NULL AND "
    "native_snapshot_sha256 IS NOT NULL AND ((kind = 'decision_required' AND task_id IS "
    "NOT NULL AND action_id IS NOT NULL AND report_id IS NULL AND budget_day IS NULL AND "
    "due_bucket IS NULL AND scheduled_for IS NULL AND notification_policy_sha256 IS NULL)"
    " OR (kind = 'work_blocked' AND task_id IS NOT NULL AND action_id IS NULL AND "
    "report_id IS NULL AND budget_day IS NULL AND due_bucket IS NULL AND scheduled_for IS"
    " NULL AND notification_policy_sha256 IS NULL) OR (kind = 'cap_exhausted' AND "
    "action_id IS NULL AND report_id IS NULL AND ((task_id IS NOT NULL AND budget_day IS "
    "NULL) OR (task_id IS NULL AND budget_day IS NOT NULL)) AND due_bucket IS NULL AND "
    "scheduled_for IS NULL AND notification_policy_sha256 IS NULL) OR (kind = "
    "'digest_due' AND action_id IS NULL AND task_id IS NULL AND budget_day IS NULL AND "
    "report_id IS NOT NULL AND due_bucket IS NOT NULL AND scheduled_for IS NOT NULL AND "
    "notification_policy_sha256 IS NOT NULL))))"
)


def add_native_event_schema(table: Table) -> None:
    """Extend one existing Table; the already constructed legacy mapper keeps its own properties."""
    for column in (
        Column("task_id", Uuid, nullable=True),
        Column("report_id", Uuid, nullable=True),
        Column("budget_day", Date, nullable=True),
        Column("native_snapshot_sha256", String(64), nullable=True),
        Column("due_bucket", String(128), nullable=True),
        Column("scheduled_for", DateTime(timezone=True), nullable=True),
        Column("notification_policy_sha256", String(64), nullable=True),
    ):
        table.append_column(column)
    previous = next(item for item in table.constraints if item.name == "ck_brain_event_kind")
    table.constraints.remove(previous)
    table.append_constraint(CheckConstraint(NATIVE_CHECK_0, name="ck_brain_event_kind"))
    table.append_constraint(CheckConstraint(NATIVE_CHECK_1, name="ck_brain_event_native_hashes"))
    table.append_constraint(CheckConstraint(NATIVE_CHECK_2, name="ck_brain_event_native_binding"))
    _native_fks(table)


def _native_fks(table: Table) -> None:
    from nexus.company.directory_models import RegisteredWork
    from nexus.company.management.operation_models import ManagementReportSnapshot
    from nexus.harness.journal_models import DailyBudget, JournalAction

    for name, local, remote in (
        (
            "task",
            ("company_id", "task_id"),
            (RegisteredWork.__table__.c.company_id, RegisteredWork.__table__.c.task_id),
        ),
        (
            "report",
            ("company_id", "report_id"),
            (
                ManagementReportSnapshot.__table__.c.company_id,
                ManagementReportSnapshot.__table__.c.report_id,
            ),
        ),
        (
            "budget",
            ("company_id", "budget_day"),
            (DailyBudget.__table__.c.company_id, DailyBudget.__table__.c.day),
        ),
        (
            "action_task",
            ("company_id", "action_id", "task_id"),
            (
                JournalAction.__table__.c.company_id,
                JournalAction.__table__.c.id,
                JournalAction.__table__.c.task_id,
            ),
        ),
    ):
        table.append_constraint(
            ForeignKeyConstraint(local, remote, name=f"fk_brain_event_native_{name}")
        )
        Index(f"ix_brain_event_native_{name}", *(table.c[column] for column in local))
