"""Explicit committed/obsolete dispositions; no decoded completion or acknowledgement permit."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.events import EventCursor
from nexus.company.management.base import require_company
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.notification_base import NotificationContract


class DraftPublication(NotificationContract):
    event_id: UUID
    state: Literal["published", "coalesced", "obsolete", "ignored"]
    reason: Literal["meaningful", "coalesced", "obsolete_native_state", "unrelated_event"]
    draft: NotificationDraft | None = None
    protection_deadlines: tuple[AwareDatetime, ...] = Field(default=(), max_length=12_800)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        require_company(self.company_id, self.draft)
        if (self.state in {"published", "coalesced"}) != (self.draft is not None):
            raise ValueError("Publication disposition must distinguish persisted body from no body")
        return self


class DraftConsumption(NotificationContract):
    cursor: EventCursor
    publications: tuple[DraftPublication, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.cursor, *self.publications)
        return self
