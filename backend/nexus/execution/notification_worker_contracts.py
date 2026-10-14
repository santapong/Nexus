"""Strict body-free durable notification descriptions; decoding publishes no native authority."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.management.base import SHA256, Symbol, require_company
from nexus.company.notifications.contracts import NotificationContract
from nexus.execution.dbos_contracts import SegmentCommand


class NotificationEnqueueResult(NotificationContract):
    """One observed canonical enqueue; queue deduplication is not permission to issue an effect."""

    command: SegmentCommand
    disposition: Literal["enqueued", "existing"]
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.command)
        return self


class NotificationSegmentResult(NotificationContract):
    """Native evidence metadata only; actual row qualification belongs to the future reader."""

    command: SegmentCommand
    status: Literal["submitted", "rejected", "outcome_unknown", "blocked"]
    receipt_id: UUID | None = None
    receipt_sha256: SHA256 | None = None
    observation_id: UUID | None = None
    observation_sha256: SHA256 | None = None
    billing: Literal["unconfirmed"] = "unconfirmed"
    observed_at: AwareDatetime
    limitations: tuple[Symbol, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def bounded_evidence(self) -> Self:
        require_company(self.company_id, self.command)
        receipt = self.receipt_id is not None
        observation = self.observation_id is not None
        if (
            receipt != (self.receipt_sha256 is not None)
            or observation != (self.observation_sha256 is not None)
            or (observation and not receipt)
            or (self.status in {"submitted", "rejected"} and not receipt)
            or len(set(self.limitations)) != len(self.limitations)
        ):
            raise ValueError("Notification result lacks exact descriptive native evidence")
        return self
