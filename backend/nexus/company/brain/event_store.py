"""Company-first ID-only outbox and monotone recipe consumer acknowledgment."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, cast
from uuid import UUID, uuid5

from sqlalchemy import Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.brain.events import EventCursor, EventKind, OutboxEvent
from nexus.company.brain.native_event_capability import native_event_capability
from nexus.company.brain.native_event_records import event_record as event_record
from nexus.company.brain.native_event_records import pending_events
from nexus.company.brain.native_event_records import read_event as read_event
from nexus.company.brain.native_event_schema import NATIVE_EVENT_FIELDS, OLD_EVENT_KINDS
from nexus.company.brain.scope_support import BrainConflictError, brain_transaction


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
    task_id: UUID | None = None,
    report_id: UUID | None = None,
    budget_day: date | None = None,
    native_snapshot_sha256: str | None = None,
    due_bucket: str | None = None,
    scheduled_for: datetime | None = None,
    notification_policy_sha256: str | None = None,
) -> OutboxEvent:
    """Caller owns the company mutex; no nested commit or model/network work is performed."""
    # Atomic append/replay boundary: actual capability, existing native references,
    # sequence allocation and explicit old/native SQL share the caller's company mutex.
    if kind not in OLD_EVENT_KINDS and not await native_event_capability(session):
        raise BrainConflictError("Native event profile is unavailable")
    existing = await session.scalar(
        select(BrainEvent).where(
            BrainEvent.company_id == scope.company_id,
            BrainEvent.deduplication_key == deduplication_key,
        )
    )
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
        task_id=task_id,
        report_id=report_id,
        budget_day=budget_day,
        native_snapshot_sha256=native_snapshot_sha256,
        due_bucket=due_bucket,
        scheduled_for=scheduled_for,
        notification_policy_sha256=notification_policy_sha256,
    )
    if existing is not None:
        old = await read_event(session, scope.company_id, existing.event_id)
        if old is None or any(
            getattr(old, name) != getattr(record, name)
            for name in (
                "kind",
                "resource",
                "source_revision_id",
                "resource_generation",
                "action_id",
                *NATIVE_EVENT_FIELDS,
            )
        ):
            raise BrainConflictError("Brain event identity conflicts with prior publication")
        return old
    statement = insert(cast(Table, BrainEvent.__table__)).values(
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
    if kind not in OLD_EVENT_KINDS:
        statement = statement.values(
            task_id=record.task_id,
            report_id=record.report_id,
            budget_day=record.budget_day,
            native_snapshot_sha256=record.native_snapshot_sha256,
            due_bucket=record.due_bucket,
            scheduled_for=record.scheduled_for,
            notification_policy_sha256=record.notification_policy_sha256,
        )
    await session.execute(statement)
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
            pending = await pending_events(
                session, scope.company_id, cursor.last_sequence, max_events
            )
            for record in pending:
                await handler.apply(session, record)
                cursor.last_sequence = record.sequence
            await session.flush()
            return EventCursor(
                company_id=scope.company_id,
                consumer=consumer,
                recipe_version=recipe_version,
                last_sequence=cursor.last_sequence,
            )
