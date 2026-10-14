"""Separate full015 event mapper; callers must qualify physical native columns before using it."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy.orm import Mapped

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.model_base import BrainBase


class NativeBrainEvent:
    """Full shared-table attributes do not mutate the legacy mapper's columns or properties."""

    company_id: Mapped[UUID]
    event_id: Mapped[UUID]
    sequence: Mapped[int]
    kind: Mapped[str]
    resource_id: Mapped[UUID]
    deduplication_key: Mapped[str]
    operation_id: Mapped[UUID]
    trace_id: Mapped[UUID]
    recorded_at: Mapped[datetime]
    source_revision_id: Mapped[UUID | None]
    resource_generation: Mapped[int | None]
    action_id: Mapped[UUID | None]
    task_id: Mapped[UUID | None]
    report_id: Mapped[UUID | None]
    budget_day: Mapped[date | None]
    native_snapshot_sha256: Mapped[str | None]
    due_bucket: Mapped[str | None]
    scheduled_for: Mapped[datetime | None]
    notification_policy_sha256: Mapped[str | None]


BrainBase.registry.map_imperatively(NativeBrainEvent, BrainEvent.__table__)
