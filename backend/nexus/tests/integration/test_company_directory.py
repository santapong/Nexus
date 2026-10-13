"""Real non-superuser PostgreSQL directory/allocation acceptance in a private test DB."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import Connection, func, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_contracts import (
    CompanyRegistration,
    DirectoryDeniedError,
    MembershipChange,
    WorkRegistration,
)
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership, RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.harness.journal_models import WorkBudget
from nexus.settings import settings

COMPANY, WORKSPACE, OWNER, ACTOR, TASK, TRACE = (UUID(int=i) for i in range(1, 7))


def control(principal: UUID = OWNER) -> CompanyControlScope:
    return CompanyControlScope(
        company_id=COMPANY, principal_id=principal, operation_id=UUID(int=9), trace_id=UUID(int=10)
    )


def work(
    task_id: UUID = TASK, *, parent: UUID | None = None, amount: str = "1.00"
) -> WorkRegistration:
    return WorkRegistration(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        task_id=task_id,
        trace_id=TRACE,
        actor_id=ACTOR,
        parent_task_id=parent,
        allocation_usd=Decimal(amount),
        allowed_principals=(ACTOR,),
    )


def migrate(connection: Connection, direction: str) -> None:
    """Use normal independent Alembic commands; no metadata stamp/create_all shortcut."""
    backend = Path(__file__).resolve().parents[3]
    config = Config(str(backend / "alembic_company.ini"))
    config.set_main_option("script_location", str(backend / "company_alembic"))
    config.attributes["connection"] = connection
    if direction == "upgrade":
        assert set(inspect(connection).get_table_names()) <= {"company_alembic_version"}
        command.upgrade(config, "head")
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
        )
    else:
        command.downgrade(config, "base")


@pytest.fixture
async def directory_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Never use the root's release DB or any existing company/legacy installation."""
    if not settings.company_test_database_url:
        pytest.skip("explicit private directory test database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_directory"
    assert settings.company_test_database_url != settings.database_url
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


async def prepare(factory: async_sessionmaker[AsyncSession]) -> PersistentCompanyDirectory:
    journal = CompanyJournal(factory)
    await journal.create_company(
        CompanyPolicy(
            company_id=COMPANY,
            owner_id=OWNER,
            policy_version="fixture-policy",
            price_version="fixture-prices",
        ),
        LedgerScope(
            company_id=COMPANY, principal_id=OWNER, task_id=UUID(int=9), trace_id=UUID(int=10)
        ),
    )
    directory = PersistentCompanyDirectory(factory)
    await directory.bootstrap(
        CompanyRegistration(company_id=COMPANY, workspace_id=WORKSPACE, owner_id=OWNER), control()
    )
    await directory.set_membership(
        MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="member"), control()
    )
    return directory


async def test_mapping_discovery_uses_current_identity_not_token_role(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    actual = await directory.lookup_principal(
        VerifiedIdentity(principal_id=ACTOR, workspace_id=WORKSPACE), task_id=TASK, trace_id=TRACE
    )
    assert actual is not None and actual.company_id == COMPANY and actual.owner_id == OWNER
    assert actual.membership_role == "member"
    unknown = await directory.lookup_principal(
        VerifiedIdentity(principal_id=ACTOR, workspace_id=UUID(int=77)),
        task_id=TASK,
        trace_id=TRACE,
    )
    assert unknown is None
    with pytest.raises(DirectoryDeniedError):
        await directory.set_membership(
            MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="owner"), control()
        )
    with pytest.raises(DirectoryDeniedError):
        await directory.set_membership(
            MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="admin"), control(ACTOR)
        )


async def test_registered_work_is_exact_idempotent_and_owner_audit_cannot_mint_it(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    first = await directory.register_work(work(), control())
    assert first.root_task_id == TASK and first.available_usd == Decimal("1.00")
    assert await directory.register_work(work(), control()) == first
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(
            work().model_copy(update={"trace_id": UUID(int=99)}), control()
        )
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(work(UUID(int=9)), control())
    assert await directory.lookup_work(COMPANY, TASK, trace_id=UUID(int=99)) is None
    assert await directory.lookup_work(UUID(int=99), TASK, trace_id=TRACE) is None


async def test_child_retry_never_consumes_parent_slice_twice(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    child = work(UUID(int=11), parent=TASK, amount="0.40")
    first = await directory.register_work(child, control())
    assert first.root_task_id == TASK
    assert await directory.register_work(child, control()) == first
    allocation = await directory.allocation(COMPANY, TASK, trace_id=TRACE)
    assert allocation is not None and allocation.delegated_usd == Decimal("0.40")
    assert allocation.available_usd == Decimal("0.60")


async def test_competing_children_cannot_overallocate_the_same_parent(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    results = await asyncio.gather(
        directory.register_work(work(UUID(int=11), parent=TASK, amount="0.60"), control()),
        directory.register_work(work(UUID(int=12), parent=TASK, amount="0.60"), control()),
        return_exceptions=True,
    )
    assert sum(isinstance(result, DirectoryDeniedError) for result in results) == 1
    allocation = await directory.allocation(COMPANY, TASK, trace_id=TRACE)
    assert allocation is not None and allocation.delegated_usd == Decimal("0.60")


async def test_parent_spent_and_unknown_holds_reduce_delegation(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    async with directory_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            WorkBudget(
                company_id=COMPANY,
                task_id=TASK,
                spent_usd=Decimal("0.30"),
                held_usd=Decimal("0.20"),
            )
        )
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(work(UUID(int=11), parent=TASK, amount="0.500001"), control())
    await directory.register_work(work(UUID(int=11), parent=TASK, amount="0.50"), control())
    allocation = await directory.allocation(COMPANY, TASK, trace_id=TRACE)
    assert allocation is not None and allocation.available_usd == Decimal(0)


async def test_current_membership_and_parent_activity_revoke_work_without_refunds(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    await directory.register_work(work(UUID(int=11), parent=TASK, amount="0.40"), control())
    await directory.set_work_active(control(), task_id=TASK, active=False)
    child = await directory.lookup_work(COMPANY, UUID(int=11), trace_id=TRACE)
    assert child is not None and not child.active
    await directory.set_work_active(control(), task_id=TASK, active=True)
    await directory.set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
        ),
        control(),
    )
    current = await directory.lookup_work(COMPANY, TASK, trace_id=TRACE)
    assert current is not None and not current.active and ACTOR not in current.allowed_principals
    allocation = await directory.allocation(COMPANY, TASK, trace_id=TRACE)
    assert allocation is not None and allocation.delegated_usd == Decimal("0.40")


async def test_directory_rls_has_no_unscoped_or_cross_company_fallback(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare(directory_factory)
    async with directory_factory() as session, session.begin():
        assert (await session.scalars(select(DirectoryCompany))).all() == []
        assert (await session.scalars(select(DirectoryMembership))).all() == []
        await session.execute(select(func.set_config("nexus.company_id", str(UUID(int=99)), True)))
        assert (await session.scalars(select(DirectoryCompany))).all() == []
        assert (await session.scalars(select(DirectoryMembership))).all() == []


async def test_database_rejects_work_identity_and_parent_allocation_resets(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    await directory.register_work(work(UUID(int=11), parent=TASK, amount="0.40"), control())
    for values in (
        {"trace_id": UUID(int=99)},
        {"allocation_usd": Decimal("2.00")},
        {"delegated_usd": Decimal(0)},
    ):
        with pytest.raises(DBAPIError):
            async with directory_factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                await session.execute(
                    update(RegisteredWork)
                    .where(RegisteredWork.company_id == COMPANY, RegisteredWork.task_id == TASK)
                    .values(**values)
                )


async def test_paused_intake_viewer_actor_and_unknown_work_cannot_mint_allowance(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    journal = CompanyJournal(directory_factory)
    scope = LedgerScope(company_id=COMPANY, principal_id=OWNER, task_id=UUID(int=9), trace_id=TRACE)
    await journal.set_paused(scope, True)
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(work(), control())
    await journal.set_paused(scope, False)
    await directory.set_membership(
        MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="viewer"),
        control(),
    )
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(work(), control())
    with pytest.raises(DirectoryDeniedError):
        await directory.set_work_active(control(), task_id=TASK, active=True)
    assert await directory.allocation(COMPANY, TASK, trace_id=TRACE) is None


async def test_owner_bootstrap_is_idempotent_and_cannot_rebind_workspace(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.bootstrap(
        CompanyRegistration(company_id=COMPANY, workspace_id=WORKSPACE, owner_id=OWNER),
        control(),
    )
    with pytest.raises(DirectoryDeniedError):
        await directory.bootstrap(
            CompanyRegistration(company_id=COMPANY, workspace_id=UUID(int=77), owner_id=OWNER),
            control(),
        )
    with pytest.raises(DirectoryDeniedError):
        await directory.bootstrap(
            CompanyRegistration(company_id=COMPANY, workspace_id=WORKSPACE, owner_id=ACTOR),
            control(ACTOR),
        )


async def test_deep_lineage_denial_rolls_back_parent_slice_without_creating_work(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    parent = TASK
    for index in range(15):
        child = UUID(int=100 + index)
        await directory.register_work(work(child, parent=parent), control())
        parent = child
    too_deep = UUID(int=200)
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(work(too_deep, parent=parent), control())
    assert await directory.lookup_work(COMPANY, too_deep, trace_id=TRACE) is None
    unchanged = await directory.allocation(COMPANY, parent, trace_id=TRACE)
    assert unchanged is not None and unchanged.available_usd == Decimal("1.00")
