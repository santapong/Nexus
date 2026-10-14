"""Current owner inbox wire values retain native work/provider facts separately."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.management.base import require_company
from nexus.company.notifications.contracts import NotificationContract, NotificationDraft
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation

MAX_INBOX_BYTES = 2_097_152


class InboxUnavailableError(ValueError):
    """Generic absence/current qualification failure; never carries source or recipient details."""


class NotificationInboxEntry(NotificationContract):
    draft: NotificationDraft
    latest_submission: NotificationProviderObservation | None = None
    latest_delivery: NotificationProviderObservation | None = None
    latest_reconciliation: NotificationProviderObservation | None = None

    @model_validator(mode="after")
    def exact_native_observations(self) -> Self:
        require_company(self.company_id, self.draft)
        for expected, value in (
            ("submission", self.latest_submission),
            ("delivery", self.latest_delivery),
            ("reconciliation", self.latest_reconciliation),
        ):
            if value is None:
                continue
            require_company(self.company_id, value)
            if (value.draft_id, value.payload_sha256, value.kind) != (
                self.draft.draft_id,
                self.draft.payload_sha256,
                expected,
            ):
                raise ValueError("Inbox observation differs from its native draft")
        return self


class NotificationInboxPage(NotificationContract):
    checked_at: AwareDatetime
    notifications: tuple[NotificationInboxEntry, ...] = Field(default=(), max_length=8)
    next_after_id: UUID | None = None

    @model_validator(mode="after")
    def exact_company(self) -> Self:
        require_company(self.company_id, *self.notifications)
        return self
