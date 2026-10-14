"""Uninstalled immutable owner draft/event declarations; no fake polymorphic subject FK."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.event_models import BrainEvent
from nexus.company.directory_models import DirectoryMembership
from nexus.company.notifications.model_base import (
    CompanyRow,
    NotificationBase,
    RecordedRow,
    scoped_fk,
)


class NotificationDraftRow(CompanyRow, RecordedRow, NotificationBase):
    __tablename__ = "company_notification_drafts"
    draft_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    subject_kind: Mapped[str] = mapped_column(String(24))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    native_state_sha256: Mapped[str] = mapped_column(String(64))
    trigger_sha256: Mapped[str] = mapped_column(String(64))
    recipient_class: Mapped[str] = mapped_column(String(16))
    recipient_owner_id: Mapped[UUID] = mapped_column(Uuid)
    recipient_policy_id: Mapped[UUID] = mapped_column(Uuid)
    recipient_policy_version: Mapped[str] = mapped_column(String(128))
    recipient_policy_sha256: Mapped[str] = mapped_column(String(64))
    recipient_policy_json: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(128))
    template_version: Mapped[str] = mapped_column(String(128))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    record_sha256: Mapped[str] = mapped_column(String(64))
    record_json: Mapped[str] = mapped_column(Text)
    due_bucket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    audit_trace_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "recipient_class", "trigger_sha256", name="uq_notification_trigger"
        ),
        UniqueConstraint(
            "company_id",
            "draft_id",
            "payload_sha256",
            "recipient_policy_sha256",
            "kind",
            name="uq_notification_draft_content",
        ),
        Index(
            "ix_notification_draft_owner",
            "company_id",
            "recipient_owner_id",
            "recorded_at",
            "draft_id",
        ),
        Index("ix_notification_draft_recorder", "company_id", "recorded_by"),
        CheckConstraint(
            "kind IN ('routine','daily','weekly') AND recipient_class = 'owner' AND "
            "subject_kind IN ('action','work','company_budget','work_budget','digest_report')",
            name="ck_notification_draft_kind",
        ),
        CheckConstraint(
            "((kind = 'routine' AND due_bucket IS NULL AND scheduled_for IS NULL "
            "AND subject_kind <> 'digest_report') OR (kind IN ('daily','weekly') "
            "AND due_bucket IS NOT NULL AND length(due_bucket) BETWEEN 1 AND 128 "
            "AND scheduled_for IS NOT NULL AND subject_kind = 'digest_report'))",
            name="ck_notification_draft_due",
        ),
        CheckConstraint(
            "native_state_sha256 ~ '^[0-9a-f]{64}$' AND trigger_sha256 ~ '^[0-9a-f]{64}$' "
            "AND recipient_policy_sha256 ~ '^[0-9a-f]{64}$' AND payload_sha256 ~ '^[0-9a-f]{64}$' "
            "AND record_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_notification_draft_hashes",
        ),
        CheckConstraint(
            "octet_length(record_json) BETWEEN 1 AND 4194304 AND "
            "octet_length(payload_json) BETWEEN 1 AND 131072 AND "
            "octet_length(recipient_policy_json) BETWEEN 1 AND 16384 AND "
            "length(policy_version) BETWEEN 1 AND 128 AND "
            "length(template_version) BETWEEN 1 AND 128 AND "
            "length(recipient_policy_version) BETWEEN 1 AND 128",
            name="ck_notification_draft_bounds",
        ),
    )


class NotificationEventLinkRow(CompanyRow, RecordedRow, NotificationBase):
    __tablename__ = "company_notification_event_links"
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_sequence: Mapped[int] = mapped_column(BigInteger)
    draft_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        Index("ix_notification_link_event", "company_id", "event_id", "event_sequence"),
        Index("ix_notification_link_draft", "company_id", "draft_id"),
        CheckConstraint("event_sequence >= 1", name="ck_notification_link_sequence"),
    )


for name, column in (("recipient", "recipient_owner_id"), ("recorder", "recorded_by")):
    scoped_fk(
        NotificationDraftRow.__table__,
        ("company_id", column),
        DirectoryMembership.__table__,
        ("company_id", "principal_id"),
        f"fk_notification_draft_{name}",
    )
scoped_fk(
    NotificationEventLinkRow.__table__,
    ("company_id", "event_id", "event_sequence"),
    BrainEvent.__table__,
    ("company_id", "event_id", "sequence"),
    "fk_notification_link_event",
)
scoped_fk(
    NotificationEventLinkRow.__table__,
    ("company_id", "draft_id"),
    NotificationDraftRow.__table__,
    ("company_id", "draft_id"),
    "fk_notification_link_draft",
)
