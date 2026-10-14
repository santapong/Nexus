"""Immutable ID-only outbox records; updates do not grant work allowance or authority."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SHA256, BrainContract, Count, Ordinal, Symbol, require_company
from nexus.company.brain.native_event_schema import NATIVE_EVENT_FIELDS, OLD_EVENT_KINDS

EventKind = Literal[
    "source_revised",
    "acl_changed",
    "claims_changed",
    "derivation_changed",
    "receipt_recorded",
    "verification_recorded",
    "decision_required",
    "work_blocked",
    "cap_exhausted",
    "digest_due",
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
    task_id: UUID | None = None
    report_id: UUID | None = None
    budget_day: date | None = None
    native_snapshot_sha256: SHA256 | None = None
    due_bucket: Symbol | None = None
    scheduled_for: AwareDatetime | None = None
    notification_policy_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def scoped_event(self) -> Self:
        require_company(self.company_id, self.resource)
        if self.kind == "source_revised" and self.source_revision_id is None:
            raise ValueError("Source revision event requires its immutable revision")
        if self.kind == "acl_changed" and self.resource_generation is None:
            raise ValueError("ACL event requires the new resource-wide generation")
        if self.kind in {"receipt_recorded", "verification_recorded"} and self.action_id is None:
            raise ValueError("Execution evidence event requires its exact action")
        self._native_shape()
        return self

    def _native_shape(self) -> None:
        if self.kind in OLD_EVENT_KINDS:
            if any(getattr(self, name) is not None for name in NATIVE_EVENT_FIELDS):
                raise ValueError("Old event kinds cannot carry native reference fields")
            return
        if (
            self.source_revision_id is not None
            or self.resource_generation is not None
            or self.native_snapshot_sha256 is None
        ):
            raise ValueError(
                "Native event requires exact native state without old source/ACL fields"
            )
        present = {
            name for name in (*NATIVE_EVENT_FIELDS, "action_id") if getattr(self, name) is not None
        }
        required = {
            "decision_required": {"action_id", "task_id", "native_snapshot_sha256"},
            "work_blocked": {"task_id", "native_snapshot_sha256"},
            "digest_due": {
                "report_id",
                "native_snapshot_sha256",
                "due_bucket",
                "scheduled_for",
                "notification_policy_sha256",
            },
        }
        if self.kind == "cap_exhausted":
            if present not in (
                {"task_id", "native_snapshot_sha256"},
                {"budget_day", "native_snapshot_sha256"},
            ):
                raise ValueError("Cap event requires exactly one native work or company/day budget")
        elif present != required[self.kind]:
            raise ValueError("Native event reference shape differs from its kind")


class EventCursor(BrainContract):
    consumer: Symbol
    recipe_version: Symbol
    last_sequence: Ordinal
