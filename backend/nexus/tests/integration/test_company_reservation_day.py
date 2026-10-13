"""Unissued held calls crossing Bangkok midnight charge the day execution starts."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, DailyBudget
from nexus.harness.journal_reservations import hold_to_effect_day
from nexus.tests.integration.test_company_atomic_enqueue import (
    Databases,
    pending,
)
from nexus.tests.integration.test_company_atomic_enqueue import (
    enqueue_database as enqueue_database,
)
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_registered_authorization import (
    NOW,
    SOURCES,
    identity,
    scope,
)
from nexus.tests.integration.test_company_registered_authorization import (
    pending as pending_action,
)


async def move(
    databases: Databases, action_id: UUID, now: datetime = NOW + timedelta(minutes=2)
) -> None:
    async with databases.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        control = await session.scalar(select(CompanyControl).with_for_update())
        assert control
        await hold_to_effect_day(session, control, scope(), action_id, now)


async def test_cross_midnight_moves_daily_hold_but_not_lifetime_work_hold(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    await journal.authorize_registered(
        scope(), command.action_id, NOW, SOURCES, identity=identity()
    )
    before = await journal.budget(scope(), NOW)
    await move(enqueue_database, command.action_id)
    await move(enqueue_database, command.action_id)
    old = await journal.budget(scope(), NOW)
    current = await journal.budget(scope(), NOW + timedelta(minutes=2))
    assert old.daily_held_usd == 0
    assert current.daily_held_usd == before.daily_held_usd
    assert current.work_held_usd == before.work_held_usd


async def test_exhausted_current_day_does_not_release_original_reservation(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    await journal.authorize_registered(
        scope(), command.action_id, NOW, SOURCES, identity=identity()
    )
    async with enqueue_database.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            DailyBudget(
                company_id=COMPANY,
                day=billing_day(NOW + timedelta(minutes=2)),
                held_usd=0,
                spent_usd=5,
            )
        )
    with pytest.raises(ValueError, match=r"current|Current"):
        await move(enqueue_database, command.action_id)
    assert (await journal.budget(scope(), NOW)).daily_held_usd > 0
    assert (await journal.budget(scope(), NOW + timedelta(minutes=2))).daily_held_usd == 0


async def test_unknown_billing_cannot_be_refunded_or_moved_to_new_day(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    await journal.authorize_registered(
        scope(), command.action_id, NOW, SOURCES, identity=identity()
    )
    await journal.reconcile(scope(), command.action_id, None)
    with pytest.raises(ValueError, match="held"):
        await move(enqueue_database, command.action_id)
    assert (await journal.budget(scope(), NOW)).daily_held_usd > 0


@pytest.mark.parametrize("actual,limit", [("4.7", "daily"), ("0.7", "work")])
async def test_same_day_unissued_hold_rechecks_caps_after_truthful_overrun(
    enqueue_database: Databases, actual: str, limit: str
) -> None:
    journal, command = await pending(enqueue_database)
    second = await pending_action(journal, key=14)
    for action_id in (command.action_id, second.action_id):
        await journal.authorize_registered(scope(), action_id, NOW, SOURCES, identity=identity())
    await journal.reconcile(scope(), command.action_id, Decimal(actual))
    before = await journal.budget(scope(), NOW)
    assert before.work_held_usd == Decimal("0.4")
    assert before.work_spent_usd == Decimal(actual)
    with pytest.raises(ValueError, match=limit):
        await move(enqueue_database, second.action_id, NOW)
    assert await journal.budget(scope(), NOW) == before
