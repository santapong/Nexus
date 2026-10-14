"""Immutable safe provider observations; no receipt/billing/acceptance rewrites."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.model_base import (
    CompanyRow,
    NotificationBase,
    RecordedRow,
    scoped_fk,
)


class NotificationObservationRow(CompanyRow, RecordedRow, NotificationBase):
    __tablename__ = "company_notification_observations"
    observation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    draft_id: Mapped[UUID] = mapped_column(Uuid)
    action_id: Mapped[UUID] = mapped_column(Uuid)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    observation_kind: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    provider_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    provider_event: Mapped[str | None] = mapped_column(String(24), nullable=True)
    delivery_state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(32))
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    receipt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_sha256: Mapped[str] = mapped_column(String(64))
    record_json: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    audit_trace_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        Index(
            "ix_notification_observation_dispatch",
            "company_id",
            "draft_id",
            "action_id",
            "payload_sha256",
        ),
        Index("ix_notification_observation_recorder", "company_id", "recorded_by"),
        Index(
            "ix_notification_observation_history",
            "company_id",
            "draft_id",
            "recorded_at",
            "observation_id",
        ),
        Index(
            "uq_notification_initial_submission",
            "company_id",
            "draft_id",
            unique=True,
            postgresql_where=text("observation_kind = 'submission'"),
        ),
        CheckConstraint(
            "observation_kind IN ('submission','delivery','reconciliation') AND "
            "delivery_state IN ('unknown','delayed','delivered','bounced','failed',"
            "'suppressed','complained')",
            name="ck_notification_observation_kind",
        ),
        CheckConstraint(
            "((observation_kind IN ('submission','reconciliation') AND outcome IN "
            "('accepted','rejected','unknown','blocked') AND provider_event IS NULL "
            "AND delivery_state = 'unknown' AND ((outcome = 'accepted' AND provider_id "
            "IS NOT NULL AND response_sha256 IS NOT NULL) OR (outcome <> 'accepted' "
            "AND provider_id IS NULL))) OR (observation_kind = 'delivery' AND provider_id "
            "IS NOT NULL AND ((outcome = 'observed' AND provider_event IS NOT NULL "
            "AND response_sha256 IS NOT NULL) OR (outcome IN ('unavailable','blocked') "
            "AND provider_event IS NULL AND delivery_state = 'unknown'))))",
            name="ck_notification_observation_binding",
        ),
        CheckConstraint(
            "provider_event IS NULL OR provider_event IN ('bounced','canceled','clicked',"
            "'complained','delivered','delivery_delayed','failed','opened','queued',"
            "'scheduled','sent','suppressed')",
            name="ck_notification_observation_event",
        ),
        CheckConstraint(
            "((provider_event IS NULL AND delivery_state = 'unknown') OR "
            "(provider_event IS NOT NULL AND ((provider_event = 'delivered' AND "
            "delivery_state = 'delivered') OR (provider_event = 'delivery_delayed' "
            "AND delivery_state = 'delayed') OR (provider_event = 'bounced' AND "
            "delivery_state = 'bounced') OR (provider_event IN ('failed','canceled') "
            "AND delivery_state = 'failed') OR (provider_event = 'suppressed' AND "
            "delivery_state = 'suppressed') OR (provider_event = 'complained' AND "
            "delivery_state = 'complained') OR (provider_event IN ('opened','clicked',"
            "'queued','scheduled','sent') AND delivery_state = 'unknown'))))",
            name="ck_notification_observation_state",
        ),
        CheckConstraint(
            "reason IN ('accepted','disabled','configuration_missing','recipient_policy',"
            "'invalid_key','provider_rejected','provider_conflict','concurrent_unknown',"
            "'network_unknown','provider_unknown','invalid_response','response_too_large',"
            "'lookup_unavailable','content_mismatch','observed') AND (provider_id IS NULL "
            "OR (receipt_id IS NOT NULL AND receipt_sha256 IS NOT NULL))",
            name="ck_notification_observation_provenance",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$' "
            "AND (response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$') AND "
            "((receipt_id IS NULL AND receipt_sha256 IS NULL) OR (receipt_id IS NOT NULL "
            "AND receipt_sha256 IS NOT NULL AND receipt_sha256 ~ '^[0-9a-f]{64}$')) AND "
            "octet_length(record_json) BETWEEN 1 AND 32768 AND length(reason) BETWEEN 1 AND 32",
            name="ck_notification_observation_shape",
        ),
    )


scoped_fk(
    NotificationObservationRow.__table__,
    ("company_id", "draft_id", "action_id", "payload_sha256"),
    NotificationDispatchRow.__table__,
    ("company_id", "draft_id", "action_id", "payload_sha256"),
    "fk_notification_observation_dispatch",
)
scoped_fk(
    NotificationObservationRow.__table__,
    ("company_id", "recorded_by"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_notification_observation_recorder",
)
