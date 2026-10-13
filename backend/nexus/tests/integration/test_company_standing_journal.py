"""Standing authority consumption has exact-action holds and durable source provenance."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.harness.standing_journal import StandingJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    control,
)
from nexus.tests.integration.test_company_standing_authority import (
    identity,
    initialized,
    migrate,
    proposal,
    standing,
)
from nexus.tests.unit.test_company_foundation import NOW


def scope(principal: UUID = ACTOR) -> LedgerScope:
    return LedgerScope(company_id=COMPANY, principal_id=principal, task_id=TASK, trace_id=TRACE)


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("explicit standing-journal disposable database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_standing_journal"
    engine = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await engine.dispose()


async def test_routine_actions_need_one_grant_and_keep_individual_holds(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    journal = StandingJournal(factory)
    for key in (800, 801, 802):
        action = proposal().model_copy(update={"action_id": UUID(int=key)})
        await journal.submit(action, scope())
        record = await journal.authorize_standing(
            scope(), action.action_id, standing().grant_id, NOW, (), identity=identity(ACTOR)
        )
        assert record.state == "authorized" and record.approval is None
    budget = await journal.budget(scope(), NOW)
    assert str(budget.work_held_usd) == "0.300000"
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert len((await session.scalars(select(ActionAuthority))).all()) == 3


async def test_replay_cannot_consume_one_standing_action_twice(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    journal = StandingJournal(factory)
    item = proposal()
    await journal.submit(item, scope())
    await journal.authorize_standing(
        scope(), item.action_id, standing().grant_id, NOW, (), identity=identity(ACTOR)
    )
    with pytest.raises(ValueError, match="consumed"):
        await journal.authorize_standing(
            scope(), item.action_id, standing().grant_id, NOW, (), identity=identity(ACTOR)
        )
    assert str((await journal.budget(scope(), NOW)).work_held_usd) == "0.100000"


async def test_revoked_grant_cannot_consume_or_hold_cost(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    journal = StandingJournal(factory)
    item = proposal()
    await journal.submit(item, scope())
    await store.revoke(standing().grant_id, control(), identity(), NOW)
    with pytest.raises(ValueError):
        await journal.authorize_standing(
            scope(), item.action_id, standing().grant_id, NOW, (), identity=identity(ACTOR)
        )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(CostHold, item.action_id) is None


async def test_owner_rejection_cannot_be_overridden_by_standing_grant(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    journal = StandingJournal(factory)
    item = proposal()
    record = await journal.submit(item, scope())
    await journal.approve_registered(
        scope(OWNER), item.action_id, record.proposal_hash, NOW, approved=False, identity=identity()
    )
    with pytest.raises(ValueError):
        await journal.authorize_standing(
            scope(), item.action_id, standing().grant_id, NOW, (), identity=identity(ACTOR)
        )


async def test_authorization_source_cannot_be_replaced_in_database(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    journal = StandingJournal(factory)
    item = proposal()
    await journal.submit(item, scope())
    await journal.authorize_standing(
        scope(), item.action_id, standing().grant_id, NOW, (), identity=identity(ACTOR)
    )
    with pytest.raises(DBAPIError):
        async with factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(update(ActionAuthority).values(grant_hash="0" * 64))
