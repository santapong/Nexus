"""TEST-only public sender grant expiry and bounded nomination of the actual final SQL clock."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications import qualified_consumer
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.qualified_consumer import ACTIONABLE
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.runtime_support import db_now
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity


async def finite_sender_grant(services: NotificationWorkerServices) -> datetime:
    bound = services.registrations.snapshot().value.registration.sender
    witness = await services.identities.current(expected_binding=bound)
    target = services.preparation.policy.target
    async with management_owner_transaction(services.factory, control(), witness.identity) as (
        session,
        _,
        _,
    ):
        resource = await session.get(BrainResource, (COMPANY, target.resource_id))
        assert resource is not None
        generation = resource.acl_generation
        expires = await db_now(session) + timedelta(seconds=10)
    saved = await ResourceAccessStore(services.factory).change(
        owner_scope(control(), witness.identity),
        witness.identity,
        ResourceAccessChange(
            company_id=COMPANY,
            resource=target,
            principal_id=OWNER,
            active=True,
            expires_at=expires,
            expected_generation=generation,
        ),
    )
    assert saved.expires_at == expires and saved.active
    return expires


async def pending_ignored_kinds(factory: async_sessionmaker[AsyncSession]) -> tuple[str, ...]:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        cursor = await session.get(
            BrainEventCursor, (COMPANY, "nexus.notifications.worker", "native-notification-read-v1")
        )
        values = tuple(
            (
                await session.scalars(
                    select(BrainEvent.kind)
                    .where(BrainEvent.sequence > (cursor.last_sequence if cursor else 0))
                    .order_by(BrainEvent.sequence)
                )
            ).all()
        )
        assert all(value not in ACTIONABLE for value in values)
        return values


def delay_final_consumer_clock(
    monkeypatch: pytest.MonkeyPatch,
    expires: datetime,
    seen: list[datetime],
) -> None:
    assert vars(qualified_consumer)["db_now"] is db_now
    original: Callable[[AsyncSession], Awaitable[datetime]] = db_now

    async def crossing(session: AsyncSession) -> datetime:
        before = await original(session)
        assert before < expires
        remaining = (expires - datetime.now(UTC)).total_seconds()
        assert 0 < remaining < 15
        await asyncio.sleep(remaining + 0.03)
        actual = await original(session)
        assert actual >= expires
        seen.append(actual)
        return actual

    monkeypatch.setattr(qualified_consumer, "db_now", crossing)


async def actual_expired_grant(services: NotificationWorkerServices, expires: datetime) -> None:
    target = services.preparation.policy.target
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        grant = await session.get(BrainResourceAccess, (COMPANY, target.resource_id, OWNER))
        assert grant is not None and grant.active and grant.expires_at == expires
        assert await db_now(session) >= expires
