"""Real PostgreSQL acceptance for standalone approval and budget persistence.

Only the explicitly configured disposable company-test database is allowed.
No API, DBOS execution or external effect is implied by these ledger tests.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, func, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.actions import ActionProposal
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.harness.journal_models import JournalAction, JournalBase
from nexus.harness.lifecycle import ActionState
from nexus.settings import settings
from nexus.tests.unit.test_company_foundation import (
    ACTOR,
    COMPANY,
    NOW,
    OWNER,
    TASK,
    TRACE,
    proposal,
)


def scope(principal: UUID = ACTOR, task_id: UUID = TASK) -> LedgerScope:
    """Construct a trusted internal test scope; it is not a remote authority token."""
    return LedgerScope(company_id=COMPANY, principal_id=principal, task_id=task_id, trace_id=TRACE)


def run_migration(connection: Connection, direction: str) -> None:
    """Apply only the new additive migration to this disposable empty database."""
    migration = Path(__file__).resolve().parents[3] / "alembic/versions/017_company_journal.py"
    spec = importlib.util.spec_from_file_location("company_journal_migration", migration)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if direction == "upgrade":
        assert inspect(connection).get_table_names() == [], "Disposable DB must be empty"
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()
    if direction == "upgrade":
        assert compare_metadata(MigrationContext.configure(connection), JournalBase.metadata) == []
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
        )


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create and destroy only migration-017 tables in an explicit test database."""
    if not settings.company_test_database_url:
        pytest.skip("Explicit disposable company-test database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database and url.database.startswith("nexus_company_test_")
    assert settings.company_test_database_url != settings.database_url
    engine = create_async_engine(url)
    app_engine = create_async_engine(url.set(username="nexus_company_app"))
    async with engine.begin() as connection:
        await connection.run_sync(run_migration, "upgrade")
    try:
        yield async_sessionmaker(app_engine, expire_on_commit=False)
    finally:
        await app_engine.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(run_migration, "downgrade")
        await engine.dispose()


async def prepare(journal: CompanyJournal, daily_cap: str = "5.00") -> ActionProposal:
    """Commit a company and pending exact proposal without any external effect."""
    await journal.create_company(
        CompanyPolicy(
            company_id=COMPANY,
            owner_id=OWNER,
            policy_version="policy-1",
            price_version="prices-1",
            daily_cap_usd=Decimal(daily_cap),
            work_cap_usd=Decimal("1.00"),
        ),
        scope(OWNER),
    )
    action = proposal()
    await journal.submit(action, scope())
    return action


async def approve(journal: CompanyJournal, action: ActionProposal) -> None:
    """Record an owner decision committed before a worker may authorize it."""
    await journal.approve(scope(OWNER, action.task_id), action.action_id, action_hash(action), NOW)


async def authorize(journal: CompanyJournal, action: ActionProposal) -> object:
    """Recheck sources and reserve spend; no tool or model is executed."""
    return await journal.authorize(
        scope(ACTOR, action.task_id), action.action_id, NOW, action.preconditions
    )


async def test_pending_approval_is_committed_and_visible_in_another_session(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    action = await prepare(journal)
    another = CompanyJournal(factory)
    record = await another.get_action(scope(), action.action_id)
    assert record.state == ActionState.AWAITING_APPROVAL
    assert record.approval is None
    await approve(journal, action)
    assert (await another.get_action(scope(), action.action_id)).approval is not None


async def test_only_exact_owner_can_approve_and_changed_payload_conflicts(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    action = await prepare(journal)
    with pytest.raises(ValueError):
        await journal.approve(scope(ACTOR), action.action_id, action_hash(action), NOW)
    with pytest.raises(ValueError):
        await journal.approve(scope(OWNER), action.action_id, "0" * 64, NOW)
    changed = ActionProposal.model_validate(action.model_dump() | {"resource": "other"})
    with pytest.raises(ValueError):
        await journal.submit(changed, scope())
    await approve(journal, action)
    with pytest.raises(ValueError):
        await journal.authorize(
            scope(), action.action_id, NOW + timedelta(hours=24), action.preconditions
        )


async def test_concurrent_workers_consume_one_approval_and_one_hold(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    action = await prepare(journal)
    await approve(journal, action)
    results = await asyncio.gather(
        authorize(journal, action), authorize(journal, action), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    summary = await journal.budget(scope(), NOW)
    assert summary.daily_held_usd == Decimal("0.50")
    assert summary.work_held_usd == Decimal("0.50")


async def test_concurrent_work_cannot_overallocate_daily_allowance(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    original = await prepare(journal, "1.00")
    first = ActionProposal.model_validate(
        original.model_dump()
        | {
            "action_id": UUID(int=20),
            "estimated_cost_usd": "0.75",
        }
    )
    second = ActionProposal.model_validate(
        first.model_dump()
        | {
            "action_id": UUID(int=21),
            "task_id": UUID(int=22),
        }
    )
    for action in (first, second):
        await journal.submit(action, scope(ACTOR, action.task_id))
        await approve(journal, action)
    results = await asyncio.gather(
        authorize(journal, first), authorize(journal, second), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert (await journal.budget(scope(), NOW)).daily_held_usd == Decimal("0.75")


async def test_owner_pause_survives_new_service_instance_and_blocks_authorization(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    action = await prepare(journal)
    await approve(journal, action)
    with pytest.raises(ValueError):
        await journal.set_paused(scope(), True)
    await journal.set_paused(scope(OWNER), True)
    resumed = CompanyJournal(factory)
    with pytest.raises(ValueError):
        await authorize(resumed, action)
    assert (await resumed.budget(scope(), NOW)).daily_held_usd == 0
    await resumed.set_paused(scope(OWNER), False)
    await authorize(resumed, action)


async def test_unknown_bill_retains_hold_and_reconciliation_is_idempotent(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    action = await prepare(journal)
    await approve(journal, action)
    await authorize(journal, action)
    await journal.reconcile(scope(), action.action_id, None)
    assert (await journal.budget(scope(), NOW)).daily_held_usd == Decimal("0.50")
    await journal.reconcile(scope(), action.action_id, Decimal("0.40"))
    await journal.reconcile(scope(), action.action_id, Decimal("0.40"))
    summary = await journal.budget(scope(), NOW)
    assert summary.daily_held_usd == 0
    assert summary.daily_spent_usd == Decimal("0.40")
    with pytest.raises(ValueError):
        await journal.reconcile(scope(), action.action_id, Decimal("0.30"))
    with pytest.raises(ValueError):
        await authorize(CompanyJournal(factory), action)


async def test_company_scope_cannot_read_foreign_action(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    journal = CompanyJournal(factory)
    action = await prepare(journal)
    foreign = LedgerScope(company_id=UUID(int=99), principal_id=OWNER, task_id=TASK, trace_id=TRACE)
    with pytest.raises(ValueError):
        await journal.get_action(foreign, action.action_id)


async def test_database_row_policy_denies_without_company_context(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare(CompanyJournal(factory))
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0


async def test_database_rejects_editing_an_action_snapshot(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    action = await prepare(CompanyJournal(factory))
    with pytest.raises(DBAPIError):
        async with factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(
                update(JournalAction)
                .where(JournalAction.id == action.action_id)
                .values(proposal_json="tampered")
            )
