"""One immutable draft-to-M1 intent binding, installed only by Root normal014."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.model_base import (
    CompanyRow,
    NotificationBase,
    RecordedRow,
    scoped_fk,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork


class NotificationDispatchRow(CompanyRow, RecordedRow, NotificationBase):
    __tablename__ = "company_notification_dispatches"
    draft_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    action_id: Mapped[UUID] = mapped_column(Uuid)
    task_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    intent_fence: Mapped[int] = mapped_column(BigInteger)
    attempt_kind: Mapped[str] = mapped_column(String(20))
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    registration_sha256: Mapped[str] = mapped_column(String(64))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    recipient_policy_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16))
    bangkok_day: Mapped[date] = mapped_column(Date)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    audit_trace_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint("company_id", "action_id", name="uq_notification_dispatch_action"),
        UniqueConstraint(
            "company_id",
            "draft_id",
            "action_id",
            "payload_sha256",
            name="uq_notification_dispatch_content",
        ),
        Index(
            "ix_notification_dispatch_draft",
            "company_id",
            "draft_id",
            "payload_sha256",
            "recipient_policy_sha256",
            "kind",
        ),
        Index("ix_notification_dispatch_work", "company_id", "task_id", "run_id"),
        Index(
            "ix_notification_dispatch_intent",
            "company_id",
            "action_id",
            "task_id",
            "trace_id",
            "run_id",
            "intent_fence",
            "attempt_kind",
            "proposal_sha256",
        ),
        Index("ix_notification_dispatch_issuer", "company_id", "issued_by"),
        Index("ix_notification_dispatch_day", "company_id", "kind", "bangkok_day", "draft_id"),
        CheckConstraint(
            "attempt_kind = 'tool_attempts' AND intent_fence >= 1 "
            "AND kind IN ('routine','daily','weekly')",
            name="ck_notification_dispatch_kind",
        ),
        CheckConstraint(
            "proposal_sha256 ~ '^[0-9a-f]{64}$' AND registration_sha256 ~ '^[0-9a-f]{64}$' "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$' "
            "AND recipient_policy_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_notification_dispatch_hashes",
        ),
        CheckConstraint(
            "idempotency_key = 'nexus-owner-' || replace(company_id::text,'-','') "
            "|| '-' || replace(draft_id::text,'-','')",
            name="ck_notification_dispatch_key",
        ),
        CheckConstraint(
            "bangkok_day = (issued_at AT TIME ZONE 'Asia/Bangkok')::date",
            name="ck_notification_dispatch_day",
        ),
    )


scoped_fk(
    NotificationDispatchRow.__table__,
    ("company_id", "draft_id", "payload_sha256", "recipient_policy_sha256", "kind"),
    NotificationDraftRow.__table__,
    ("company_id", "draft_id", "payload_sha256", "recipient_policy_sha256", "kind"),
    "fk_notification_dispatch_draft",
)
scoped_fk(
    NotificationDispatchRow.__table__,
    ("company_id", "task_id", "run_id"),
    ExecutionWork.__table__,
    ("company_id", "task_id", "run_id"),
    "fk_notification_dispatch_work",
)
scoped_fk(
    NotificationDispatchRow.__table__,
    (
        "company_id",
        "action_id",
        "task_id",
        "trace_id",
        "run_id",
        "intent_fence",
        "attempt_kind",
        "proposal_sha256",
    ),
    EffectIntent.__table__,
    (
        "company_id",
        "action_id",
        "task_id",
        "trace_id",
        "run_id",
        "intent_fence",
        "attempt_kind",
        "proposal_hash",
    ),
    "fk_notification_dispatch_intent",
    deferred=True,
)
scoped_fk(
    NotificationDispatchRow.__table__,
    ("company_id", "issued_by"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_notification_dispatch_issuer",
)
