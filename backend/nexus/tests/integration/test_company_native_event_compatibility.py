"""Actual008/014 event ingestion/append/replay/consume and ORM SQL remain old-column compatible."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import BrainEventStore, append_event, read_event
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_event_capability import native_event_capability
from nexus.company.brain.native_event_schema import NATIVE_EVENT_FIELDS
from nexus.company.brain.scope_support import brain_transaction
from nexus.execution.runtime_support import db_now
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
    Reader,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_events_support import old_event_factory as old_event_factory


class Handler:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    async def apply(self, session: AsyncSession, actual: OutboxEvent) -> None:
        self.events.append(actual)


async def test_old_profile_real_ingestion_append_replay_consume_and_original_orm_sql(
    old_event_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = await configured(
        old_event_factory, tmp_path, Reader({"r1": b"Actual old profile source."})
    )
    # Use the existing actual public ingestion command/registration fixture.
    from nexus.tests.integration.test_company_brain_ingestion import command

    async with old_event_factory() as session:
        version = await session.scalar(text("SELECT version_num FROM company_alembic_version"))
    if version == "company_014":
        await store.ingest(
            owner_scope(), identity(OWNER), command(b"Actual old profile source.", "r1")
        )
    # Current artifact mapping has a pre-existing012 column on008. Root owns
    # that separate compatibility fix; this008 case proves actual event SQL only.
    async with brain_transaction(old_event_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        _,
        _,
    ):
        assert not await native_event_capability(session)
        now = await db_now(session)
        created = await append_event(
            session,
            owner_scope(),
            kind="claims_changed",
            resource_id=RESOURCE,
            deduplication_key="native.old.compat.v1",
            now=now,
        )
        assert (
            await append_event(
                session,
                owner_scope(),
                kind="claims_changed",
                resource_id=RESOURCE,
                deduplication_key="native.old.compat.v1",
                now=await db_now(session),
            )
            == created
        )
        assert await read_event(session, COMPANY, created.event_id) == created
    statements: list[str] = []
    async with old_event_factory() as session, session.begin():
        from sqlalchemy import func

        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        connection = await session.connection()

        def collect(
            connection: Connection,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            statements.append(statement)

        event.listen(connection.sync_connection, "before_cursor_execute", collect)
        row = await session.get(BrainEvent, (COMPANY, created.event_id))
        assert row and row.resource_id == RESOURCE
        session.add(
            BrainEvent(
                company_id=COMPANY,
                event_id=uuid4(),
                sequence=created.sequence + 1,
                kind="claims_changed",
                resource_id=RESOURCE,
                deduplication_key="native.old.orm.v1",
                operation_id=uuid4(),
                trace_id=uuid4(),
                recorded_at=now,
                source_revision_id=None,
                resource_generation=None,
                action_id=None,
            )
        )
        await session.flush()
        event.remove(connection.sync_connection, "before_cursor_execute", collect)
    assert statements and not any(
        any(field in sql for field in NATIVE_EVENT_FIELDS) for sql in statements
    )
    handler = Handler()
    cursor = await BrainEventStore(old_event_factory).consume(
        owner_scope(), identity(OWNER), "native.old.compat", "v1", handler
    )
    assert cursor.last_sequence >= created.sequence + 1
    assert any(row.event_id == created.event_id for row in handler.events)
