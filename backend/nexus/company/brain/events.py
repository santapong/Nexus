"""Immutable ID-only outbox records; updates do not grant work allowance or authority."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainContract, Count, Ordinal, Symbol, require_company

EventKind = Literal[
    "source_revised",
    "acl_changed",
    "claims_changed",
    "derivation_changed",
    "receipt_recorded",
    "verification_recorded",
]


class OutboxEvent(BrainContract):
    event_id: UUID
    sequence: Count
    kind: EventKind
    resource: ResourceRef
    deduplication_key: Symbol
    operation_id: UUID
    trace_id: UUID
    recorded_at: AwareDatetime
    source_revision_id: UUID | None = None
    resource_generation: Count | None = None
    action_id: UUID | None = None

    @model_validator(mode="after")
    def scoped_event(self) -> Self:
        require_company(self.company_id, self.resource)
        if self.kind == "source_revised" and self.source_revision_id is None:
            raise ValueError("Source revision event requires its immutable revision")
        if self.kind == "acl_changed" and self.resource_generation is None:
            raise ValueError("ACL event requires the new resource-wide generation")
        if self.kind in {"receipt_recorded", "verification_recorded"} and self.action_id is None:
            raise ValueError("Execution evidence event requires its exact action")
        return self


class EventCursor(BrainContract):
    consumer: Symbol
    recipe_version: Symbol
    last_sequence: Ordinal
