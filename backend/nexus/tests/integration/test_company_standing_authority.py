"""Real owner-issued grant persistence and same-transaction current-state denial."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
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
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_models import DirectoryMembership
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget
from nexus.harness.standing_contracts import StandingGrant, WorkAuthority
from nexus.harness.standing_models import StandingAuthorityGrant, StandingWorkAuthority
from nexus.harness.standing_store import StandingAuthorityStore, require_standing_authority
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
    control,
    prepare,
    work,
)
from nexus.tests.unit.test_company_foundation import NOW
from nexus.tests.unit.test_company_standing_authority import CHARTER, GRANT, PLAN


def authority() -> WorkAuthority:
    return WorkAuthority(
        company_id=COMPANY,
        task_id=TASK,
        plan_id=PLAN,
        plan_revision=1,
        charter_id=CHARTER,
        charter_revision=1,
    )


def standing() -> StandingGrant:
    return StandingGrant(
        **authority().model_dump(),
        grant_id=GRANT,
        owner_id=OWNER,
        actor_id=ACTOR,
        policy_version="fixture-policy",
        price_version="fixture-prices",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=8),
        max_action_cost_usd=Decimal("0.50"),
        permissions=(
            {"tool": "fake.internal.draft.v1", "tool_version": "v1", "resource": "fixture:report"},
        ),
    )


def proposal() -> ActionProposal:
    return ActionProposal(
        company_id=COMPANY,
        action_id=UUID(int=800),
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        revision=1,
        tool="fake.internal.draft.v1",
        tool_version="v1",
        resource="fixture:report",
        parameters={"draft": "offline fixture"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.10"),
    )


def identity(principal_id: UUID = OWNER) -> VerifiedIdentity:
    return VerifiedIdentity(principal_id=principal_id, workspace_id=WORKSPACE)


def migrate(connection: Connection, direction: str) -> None:
    backend = Path(__file__).resolve().parents[3]
    config = Config(str(backend / "alembic_company.ini"))
    config.set_main_option("script_location", str(backend / "company_alembic"))
    config.attributes["connection"] = connection
    if direction == "upgrade":
        assert set(inspect(connection).get_table_names()) <= {"company_alembic_version"}
        command.upgrade(config, "head")
        assert "company_standing_grants" in inspect(connection).get_table_names()
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
        )
    else:
        command.downgrade(config, "base")


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("Explicit private standing test DB is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_standing"
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


async def initialized(factory: async_sessionmaker[AsyncSession]) -> StandingAuthorityStore:
    directory = await prepare(factory)
    await directory.register_work(work(), control())
    store = StandingAuthorityStore(factory)
    await store.bind_work(authority(), control(), identity())
    await store.issue(standing(), control(), identity(), NOW)
    return store


async def require_grant(
    factory: async_sessionmaker[AsyncSession], action: ActionProposal | None = None
) -> None:
    item = action or proposal()
    scope = LedgerScope(
        company_id=COMPANY, principal_id=ACTOR, task_id=item.task_id, trace_id=item.trace_id
    )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.scalar(
            select(CompanyControl).where(CompanyControl.company_id == COMPANY).with_for_update()
        )
        assert current is not None
        await require_standing_authority(
            session, current, item, scope, identity(ACTOR), GRANT, NOW, ()
        )


async def test_one_owner_grant_authorizes_multiple_internal_actions_without_minting_holds(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    await require_grant(factory)
    other = ActionProposal.model_validate(proposal().model_dump() | {"action_id": UUID(int=801)})
    await require_grant(factory, other)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(CostHold)) == 0


async def test_exact_issue_replay_does_not_reactivate_or_renew_a_revoked_grant(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    first = await store.issue(standing(), control(), identity(), NOW)
    await store.revoke(GRANT, control(), identity(), NOW + timedelta(minutes=1))
    repeated = await store.issue(standing(), control(), identity(), NOW + timedelta(minutes=2))
    assert not repeated.active and repeated.grant == first.grant
    assert repeated.revoked_at == NOW + timedelta(minutes=1)
    with pytest.raises(ValueError):
        await require_grant(factory)


async def test_current_membership_and_revoked_parent_disable_existing_grant(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    directory = await prepare(factory)
    await directory.set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
        ),
        control(),
    )
    with pytest.raises(ValueError):
        await require_grant(factory)
    await directory.set_membership(
        MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="member"), control()
    )
    await directory.set_work_active(control(), task_id=TASK, active=False)
    with pytest.raises(ValueError):
        await require_grant(factory)
    assert store is not None


async def test_owner_declaration_requires_current_actual_owner_membership(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    with pytest.raises(ValueError):
        await store.bind_work(authority(), control(ACTOR), identity(ACTOR))
    with pytest.raises(ValueError):
        await store.revoke(GRANT, control(ACTOR), identity(ACTOR), NOW)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await session.execute(
            update(DirectoryMembership)
            .where(
                DirectoryMembership.company_id == COMPANY, DirectoryMembership.principal_id == OWNER
            )
            .values(membership_active=False)
        )
    with pytest.raises(ValueError):
        await store.revoke(GRANT, control(), identity(), NOW)
    with pytest.raises(ValueError):
        await require_grant(factory)


async def test_binding_revision_changes_invalidate_grants_without_modifying_snapshot(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    changed = WorkAuthority.model_validate(authority().model_dump() | {"plan_revision": 2})
    await store.bind_work(changed, control(), identity())
    assert await store.bind_work(changed, control(), identity()) == changed
    with pytest.raises(ValueError):
        await store.bind_work(authority(), control(), identity())
    with pytest.raises(ValueError):
        await require_grant(factory)


async def test_pause_unknown_work_and_new_actor_cannot_reuse_grant(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    for changes in ({"task_id": UUID(int=999)}, {"actor_id": OWNER}, {"tool": "send_email"}):
        with pytest.raises(ValueError):
            await require_grant(
                factory, ActionProposal.model_validate(proposal().model_dump() | changes)
            )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await session.execute(
            update(CompanyControl).where(CompanyControl.company_id == COMPANY).values(paused=True)
        )
    with pytest.raises(ValueError):
        await require_grant(factory)


async def test_database_rejects_snapshot_edits_reactivation_and_binding_revision_rollback(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    await store.bind_work(
        WorkAuthority.model_validate(authority().model_dump() | {"plan_revision": 2}),
        control(),
        identity(),
    )
    await store.revoke(GRANT, control(), identity(), NOW)
    for statement in (
        update(StandingAuthorityGrant)
        .where(StandingAuthorityGrant.grant_id == GRANT)
        .values(snapshot_json="{}"),
        update(StandingAuthorityGrant)
        .where(StandingAuthorityGrant.grant_id == GRANT)
        .values(active=True, revoked_at=None),
        update(StandingAuthorityGrant)
        .where(StandingAuthorityGrant.grant_id == GRANT)
        .values(revoked_at=NOW + timedelta(minutes=1)),
        update(StandingWorkAuthority)
        .where(StandingWorkAuthority.company_id == COMPANY)
        .values(plan_revision=1),
    ):
        with pytest.raises(DBAPIError):
            async with factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                await session.execute(statement)


async def test_revoke_and_effect_validation_share_the_company_lock(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.scalar(
            select(CompanyControl).where(CompanyControl.company_id == COMPANY).with_for_update()
        )
        assert current is not None
        revoke = asyncio.create_task(store.revoke(GRANT, control(), identity(), NOW))
        try:
            _, pending = await asyncio.wait({revoke}, timeout=0.05)
            assert pending == {revoke}
            scope = LedgerScope(
                company_id=COMPANY, principal_id=ACTOR, task_id=TASK, trace_id=TRACE
            )
            await require_standing_authority(
                session, current, proposal(), scope, identity(ACTOR), GRANT, NOW, ()
            )
            await session.commit()
        except BaseException:
            revoke.cancel()
            await asyncio.gather(revoke, return_exceptions=True)
            raise
    await revoke
    with pytest.raises(ValueError):
        await require_grant(factory)


async def test_cross_company_rls_and_revocation_never_refund_existing_cost_totals(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = await initialized(factory)
    async with factory() as session, session.begin():
        assert await session.scalar(select(func.count()).select_from(StandingAuthorityGrant)) == 0
        await session.execute(select(func.set_config("nexus.company_id", str(UUID(int=999)), True)))
        assert await session.scalar(select(func.count()).select_from(StandingWorkAuthority)) == 0
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            WorkBudget(
                company_id=COMPANY,
                task_id=TASK,
                held_usd=Decimal("0.20"),
                spent_usd=Decimal("0.10"),
            )
        )
        session.add(
            DailyBudget(
                company_id=COMPANY,
                day=NOW.date(),
                held_usd=Decimal("0.20"),
                spent_usd=Decimal("0.10"),
            )
        )
    await store.revoke(GRANT, control(), identity(), NOW)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        totals = await session.get(WorkBudget, (COMPANY, TASK))
        assert totals is not None and (totals.held_usd, totals.spent_usd) == (
            Decimal("0.20"),
            Decimal("0.10"),
        )


async def test_revoked_parent_disables_child_grant_without_parent_budget_refund(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(factory)
    await directory.register_work(work(), control())
    child = UUID(int=900)
    await directory.register_work(work(child, parent=TASK, amount="0.40"), control())
    store = StandingAuthorityStore(factory)
    child_binding = WorkAuthority.model_validate(authority().model_dump() | {"task_id": child})
    child_grant = StandingGrant.model_validate(
        standing().model_dump() | {"task_id": child, "max_action_cost_usd": "0.20"}
    )
    await store.bind_work(child_binding, control(), identity())
    await store.issue(child_grant, control(), identity(), NOW)
    child_action = ActionProposal.model_validate(proposal().model_dump() | {"task_id": child})
    await require_grant(factory, child_action)
    await directory.set_work_active(control(), task_id=TASK, active=False)
    with pytest.raises(ValueError):
        await require_grant(factory, child_action)
    allocation = await directory.allocation(COMPANY, TASK, trace_id=TRACE)
    assert allocation is not None and allocation.delegated_usd == Decimal("0.40")


async def test_corrupted_false_owner_actor_role_cannot_receive_a_new_grant(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await initialized(factory)
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await session.execute(
            update(DirectoryMembership)
            .where(
                DirectoryMembership.company_id == COMPANY, DirectoryMembership.principal_id == ACTOR
            )
            .values(role="owner")
        )
    store = StandingAuthorityStore(factory)
    new_grant = StandingGrant.model_validate(standing().model_dump() | {"grant_id": UUID(int=901)})
    with pytest.raises(ValueError):
        await store.issue(new_grant, control(), identity(), NOW)
