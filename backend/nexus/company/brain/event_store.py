"""Company-first ID-only outbox and monotone recipe consumer acknowledgment."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, cast
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.brain.events import EventCursor, EventKind, OutboxEvent
from nexus.company.brain.scope_support import BrainConflictError, brain_transaction


def event_record(row: BrainEvent) -> OutboxEvent:
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
    )


async def append_event(
    session: AsyncSession,
    scope: BrainReadScope,
    *,
    kind: EventKind,
    resource_id: UUID,
    deduplication_key: str,
    now: datetime,
    source_revision_id: UUID | None = None,
    resource_generation: int | None = None,
    action_id: UUID | None = None,
) -> OutboxEvent:
    """Caller owns the company mutex; no nested commit or model/network work is performed."""
    existing = await session.scalar(
        select(BrainEvent).where(
            BrainEvent.company_id == scope.company_id,
            BrainEvent.deduplication_key == deduplication_key,
        )
    )
    if existing is not None:
        if (
            existing.kind,
            existing.resource_id,
            existing.source_revision_id,
            existing.resource_generation,
            existing.action_id,
        ) != (kind, resource_id, source_revision_id, resource_generation, action_id):
            raise BrainConflictError("Brain event identity conflicts with prior publication")
        return event_record(existing)
    sequence = await session.scalar(
        select(func.max(BrainEvent.sequence)).where(BrainEvent.company_id == scope.company_id)
    )
    record = OutboxEvent(
        company_id=scope.company_id,
        event_id=uuid5(scope.company_id, deduplication_key),
        sequence=(sequence or 0) + 1,
        kind=kind,
        resource=ResourceRef(company_id=scope.company_id, resource_id=resource_id),
        deduplication_key=deduplication_key,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
        recorded_at=now,
        source_revision_id=source_revision_id,
        resource_generation=resource_generation,
        action_id=action_id,
    )
    session.add(
        BrainEvent(
            company_id=record.company_id,
            event_id=record.event_id,
            sequence=record.sequence,
            kind=record.kind,
            resource_id=resource_id,
            deduplication_key=record.deduplication_key,
            operation_id=record.operation_id,
            trace_id=record.trace_id,
            recorded_at=record.recorded_at,
            source_revision_id=record.source_revision_id,
            resource_generation=record.resource_generation,
            action_id=record.action_id,
        )
    )
    await session.flush()
    return record


class BrainEventHandler(Protocol):
    """Server-owned bounded DB/cache invalidator; no paid calls, grant or execution publication."""

    async def apply(self, session: AsyncSession, event: OutboxEvent) -> None: ...


class BrainEventStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def consume(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        consumer: str,
        recipe_version: str,
        handler: BrainEventHandler,
        *,
        max_events: int = 32,
    ) -> EventCursor:
        """A rollback cannot acknowledge publication; the next run sees the same pending event."""
        if type(max_events) is not int or not 1 <= max_events <= 32:
            raise ValueError("Brain event batch must contain 1..32 records")
        initial = EventCursor(
            company_id=scope.company_id,
            consumer=consumer,
            recipe_version=recipe_version,
            last_sequence=0,
        )
        async with brain_transaction(self._factory, scope, identity, owner=True) as (session, _, _):
            cursor = await session.get(
                BrainEventCursor, (scope.company_id, consumer, recipe_version)
            )
            if cursor is None:
                cursor = BrainEventCursor(
                    company_id=scope.company_id,
                    consumer=initial.consumer,
                    recipe_version=initial.recipe_version,
                    last_sequence=0,
                )
                session.add(cursor)
            pending = (
                await session.scalars(
                    select(BrainEvent)
                    .where(
                        BrainEvent.company_id == scope.company_id,
                        BrainEvent.sequence > cursor.last_sequence,
                    )
                    .order_by(BrainEvent.sequence)
                    .limit(max_events)
                )
            ).all()
            for row in pending:
                await handler.apply(session, event_record(row))
                cursor.last_sequence = row.sequence
            await session.flush()
            return EventCursor(
                company_id=scope.company_id,
                consumer=consumer,
                recipe_version=recipe_version,
                last_sequence=cursor.last_sequence,
            )
