"""Native signal declarations retain old serialization and convey no execution authority."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_serializer, model_validator

from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.base import SHA256, SourceTime, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.digest_bindings import NativeDigestBinding
from nexus.company.notifications.notification_base import NotificationContract


class CurrentWorkAcceptance(NotificationContract):
    """Resolved native shape; actual protected proof/source qualification remains mandatory."""

    __module__ = "nexus.company.notifications.contracts"
    acceptance: WorkAcceptance

    @model_validator(mode="after")
    def exact_work(self) -> Self:
        require_company(self.company_id, self.acceptance)
        if self.acceptance.verdict != "pass":
            raise ValueError("Current accepted work requires exact native independent pass shape")
        return self

    @property
    def work(self) -> RunBinding:
        return self.acceptance.target.author

    @property
    def acceptance_sha256(self) -> str:
        return canonical_sha256(self.acceptance)


SignalKind = Literal[
    "decision_required",
    "blocked",
    "failed",
    "cap_exhausted",
    "work_accepted",
    "idle",
    "unchanged",
    "candidate",
    "metric_satisfied",
    "digest_due",
]


class NativeNotificationSignal(NotificationContract):
    """Trusted resolver data; caller declarations cannot grant meaningfulness or permission."""

    __module__ = "nexus.company.notifications.contracts"
    event_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    subject_id: UUID
    kind: SignalKind
    state_sha256: SHA256
    source_event: SourceTime
    observed_at: AwareDatetime
    acceptance: CurrentWorkAcceptance | None = None
    budget_day: date | None = Field(default=None, exclude_if=lambda value: value is None)
    digest: NativeDigestBinding | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_serializer("budget_day")
    def exact_budget_day(self, value: date | None) -> str | None:
        return value.isoformat() if value is not None else None

    @model_validator(mode="after")
    def exact_subject(self) -> Self:
        require_company(self.company_id, self.acceptance, self.digest)
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("Notification event identities must be unique")
        if self.acceptance is not None and (
            self.kind != "work_accepted" or self.subject_id != self.acceptance.work.task_id
        ):
            raise ValueError("Acceptance must bind the exact notified native work")
        if self.budget_day is not None and (
            self.kind != "cap_exhausted" or self.subject_id != self.company_id
        ):
            raise ValueError("Company budget signal requires its actual company/day subject")
        if (self.kind == "digest_due") != (self.digest is not None) or (
            self.digest is not None and self.subject_id != self.digest.report_id
        ):
            raise ValueError("Digest signal requires its exact registered native report binding")
        return self
