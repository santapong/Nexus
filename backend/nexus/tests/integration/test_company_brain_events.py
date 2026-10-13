"""Transactional ID-only outbox replay advances a consumer only after its bounded handler."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.brain.event_store import BrainEventStore
from nexus.company.brain.events import OutboxEvent
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_brain_ingestion import ingest_factory as ingest_factory
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def test_exact_source_replay_does_not_duplicate_events_or_consumer_publication(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    raw = b"source data remains outside event payload"
    source = await configured(ingest_factory, tmp_path, Reader({"r1": raw}))
    await source.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    await source.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    calls = []

    class Handler:
        async def apply(self, session: AsyncSession, event: OutboxEvent) -> None:
            assert session.in_transaction()
            assert "source data" not in event.model_dump_json()
            calls.append(event.event_id)

    events = BrainEventStore(ingest_factory)
    first = await events.consume(
        owner_scope(), identity(OWNER), "fixture.cache", "cache-v1", Handler()
    )
    second = await events.consume(
        owner_scope(), identity(OWNER), "fixture.cache", "cache-v1", Handler()
    )
    assert second == first
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        count = await session.scalar(select(func.count()).select_from(BrainEvent))
    assert len(calls) == count == first.last_sequence


async def test_failed_consumer_does_not_ack_and_retry_processes_same_event_identity(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    raw = b"event replay keeps original source"
    source = await configured(ingest_factory, tmp_path, Reader({"r1": raw}))
    await source.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    seen = []

    class Failure:
        async def apply(self, session: AsyncSession, event: OutboxEvent) -> None:
            seen.append(event.event_id)
            raise RuntimeError("intentional pre-ack failure")

    events = BrainEventStore(ingest_factory)
    with pytest.raises(RuntimeError):
        await events.consume(owner_scope(), identity(OWNER), "fixture.retry", "cache-v1", Failure())
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainEventCursor)) == 0

    class Success:
        async def apply(self, session: AsyncSession, event: OutboxEvent) -> None:
            seen.append(event.event_id)

    advanced = await events.consume(
        owner_scope(), identity(OWNER), "fixture.retry", "cache-v1", Success()
    )
    assert advanced.last_sequence > 0 and seen[0] == seen[1]
