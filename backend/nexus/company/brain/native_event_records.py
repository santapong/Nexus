"""Qualified full event projections while preserving the original legacy mapper."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.events import EventKind, OutboxEvent
from nexus.company.brain.native_event_capability import native_event_capability
from nexus.company.brain.native_event_models import NativeBrainEvent
from nexus.company.brain.native_event_schema import OLD_EVENT_KINDS
from nexus.company.brain.scope_support import BrainDeniedError


def event_record(row: BrainEvent | NativeBrainEvent) -> OutboxEvent:
    """Project actual loaded columns; a new kind through the old mapper is unavailable."""
    if row.kind not in OLD_EVENT_KINDS and not isinstance(row, NativeBrainEvent):
        raise BrainDeniedError("Native event references were not qualified and loaded")
    native = row if isinstance(row, NativeBrainEvent) else None
    return OutboxEvent(
        company_id=row.company_id,
        event_id=row.event_id,
        sequence=row.sequence,
        kind=cast(EventKind, row.kind),
        resource=ResourceRef(company_id=row.company_id, resource_id=row.resource_id),
        deduplication_key=row.deduplication_key,
        operation_id=row.operation_id,
        trace_id=row.trace_id,
        recorded_at=row.recorded_at,
        source_revision_id=row.source_revision_id,
        resource_generation=row.resource_generation,
        action_id=row.action_id,
        task_id=native.task_id if native else None,
        report_id=native.report_id if native else None,
        budget_day=native.budget_day if native else None,
        native_snapshot_sha256=native.native_snapshot_sha256 if native else None,
        due_bucket=native.due_bucket if native else None,
        scheduled_for=native.scheduled_for if native else None,
        notification_policy_sha256=native.notification_policy_sha256 if native else None,
    )


async def read_event(session: AsyncSession, company_id: UUID, event_id: UUID) -> OutboxEvent | None:
    """Read an exact actual event; callers retain their actual mutex/signed source authorization."""
    if await native_event_capability(session):
        native = await session.get(NativeBrainEvent, (company_id, event_id))
        return event_record(native) if native else None
    old = await session.get(BrainEvent, (company_id, event_id))
    return event_record(old) if old else None


async def pending_events(
    session: AsyncSession,
    company_id: UUID,
    after_sequence: int,
    max_events: int,
) -> tuple[OutboxEvent, ...]:
    """Bounded compatible stream read; only actual015 may select the new native columns."""
    if await native_event_capability(session):
        rows = (
            await session.scalars(
                select(NativeBrainEvent)
                .where(
                    NativeBrainEvent.company_id == company_id,
                    NativeBrainEvent.sequence > after_sequence,
                )
                .order_by(NativeBrainEvent.sequence)
                .limit(max_events)
            )
        ).all()
        return tuple(event_record(row) for row in rows)
    old = (
        await session.scalars(
            select(BrainEvent)
            .where(
                BrainEvent.company_id == company_id,
                BrainEvent.sequence > after_sequence,
            )
            .order_by(BrainEvent.sequence)
            .limit(max_events)
        )
    ).all()
    return tuple(event_record(row) for row in old)
