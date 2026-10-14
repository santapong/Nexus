"""Exclusive disposable native authorization fixture with no provider or claim."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.management.plans import RunBinding
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
    PreparedNotification,
)
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CostHold
from nexus.harness.limits import LoopCounters
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_native_profile_fixture import SYMBOL, NotificationNativeScenario
from nexus.tests.notification_worker_credential_fixture import native_decision_draft


@pytest.fixture
async def worker_authorization_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Only Root's new assigned database permits this install and normal teardown."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notification_worker_authorization"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class WorkerAuthorizationCase:
    native: NotificationNativeScenario
    preparation: ManagedNotificationPreparation
    selection: NativeNotificationSelection
    binding: RunBinding
    prepared: PreparedNotification


@dataclass(frozen=True)
class AuthorizationFacts:
    action: ActionRecord
    holds: int
    intents: int
    slots: int
    hold_states: tuple[tuple[str, Decimal, Decimal | None], ...]
    counters: LoopCounters


async def authorization_case(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    approved: bool = True,
    approval_age: timedelta = timedelta(0),
) -> WorkerAuthorizationCase:
    """Real prepared sender gets an exact owner decision; nothing is authorized or issued."""
    native, drafts, selection, source = await native_decision_draft(factory, root)
    preparation = ManagedNotificationPreparation(
        factory,
        drafts,
        native.catalog,
        native.artifacts,
        native.freshness,
        policy=NotificationPreparationPolicy(
            enabled=True,
            target=native.catalog.notification_profiles[0].target_resource,
            resource_symbol=SYMBOL,
        ),
    )
    prepared = await preparation.prepare(control(), identity(OWNER), selection)
    action = prepared.action.proposal
    assert action.action_id != source.action_id
    assert type(approved) is bool
    if approved:
        await CompanyJournal(factory).approve_registered(
            native.scope,
            action.action_id,
            action_hash(action),
            datetime.now(UTC) - approval_age,
            identity=identity(OWNER),
        )
    return WorkerAuthorizationCase(native, preparation, selection, native.sender, prepared)


async def authorization_facts(
    factory: async_sessionmaker[AsyncSession], case: WorkerAuthorizationCase
) -> AuthorizationFacts:
    """Read actual scoped action, reservations and issuance facts without seeding operative rows."""
    record = await CompanyJournal(factory).get_action(
        case.native.scope, case.prepared.action.proposal.action_id
    )
    work = await case.native.runtime.get(case.native.scope, identity(OWNER))
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        counts = []
        for model in (CostHold, EffectIntent, NotificationDispatchRow):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.company_id == COMPANY)
            )
            assert count is not None
            counts.append(count)
        holds = (
            await session.scalars(
                select(CostHold).where(CostHold.company_id == COMPANY).order_by(CostHold.action_id)
            )
        ).all()
        hold_states = tuple((row.state, row.amount_usd, row.actual_usd) for row in holds)
    return AuthorizationFacts(record, counts[0], counts[1], counts[2], hold_states, work.counters)
