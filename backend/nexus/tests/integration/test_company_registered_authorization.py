"""Exact registered authority and lifetime cost reservations in private PostgreSQL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.directory_contracts import (
    CompanyRegistration,
    DirectoryDeniedError,
    MembershipChange,
)
from nexus.company.directory_models import DirectoryCompany, WorkPrincipal
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import ActionRecord, CompanyPolicy, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold
from nexus.harness.lifecycle import ActionState
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
    control,
    migrate,
    work,
)

NOW = datetime(2026, 10, 13, 16, 59, tzinfo=UTC)
CHILD = UUID(int=11)
SOURCES = (ResourceRevision(resource="fixture:stockflow", revision="head-1"),)


def scope(task: UUID = TASK, principal: UUID = ACTOR) -> LedgerScope:
    return LedgerScope(company_id=COMPANY, principal_id=principal, task_id=task, trace_id=TRACE)


def identity(principal: UUID = ACTOR, workspace: UUID = WORKSPACE) -> VerifiedIdentity:
    return VerifiedIdentity(principal_id=principal, workspace_id=workspace)


@pytest.fixture
async def governed_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("explicit private governance test DB is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_governance"
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


async def prepare(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[CompanyJournal, PersistentCompanyDirectory]:
    journal = CompanyJournal(factory)
    await journal.create_company(
        CompanyPolicy(
            company_id=COMPANY, owner_id=OWNER, policy_version="policy-1", price_version="prices-1"
        ),
        scope(principal=OWNER),
    )
    directory = PersistentCompanyDirectory(factory)
    await directory.bootstrap(
        CompanyRegistration(company_id=COMPANY, owner_id=OWNER, workspace_id=WORKSPACE), control()
    )
    await directory.set_membership(
        MembershipChange(company_id=COMPANY, principal_id=ACTOR, role="member"), control()
    )
    await directory.register_work(work(), control())
    return journal, directory


async def pending(
    journal: CompanyJournal,
    *,
    key: int = 100,
    task: UUID = TASK,
    amount: str = "0.40",
    decision: bool = True,
) -> ActionProposal:
    action = ActionProposal(
        company_id=COMPANY,
        action_id=UUID(int=key),
        task_id=task,
        trace_id=TRACE,
        actor_id=ACTOR,
        revision=1,
        tool="workspace.patch",
        tool_version="1",
        resource="fixture:stockflow",
        parameters={"path": "readiness.md", "text": "draft"},
        preconditions=SOURCES,
        policy_version="policy-1",
        price_version="prices-1",
        estimated_cost_usd=Decimal(amount),
    )
    await journal.submit(action, scope(task))
    if decision:
        await journal.approve(scope(task, OWNER), action.action_id, action_hash(action), NOW)
    return action


async def authorize(
    journal: CompanyJournal, action: ActionProposal, *, now: datetime = NOW
) -> ActionRecord:
    return await journal.authorize_registered(
        scope(action.task_id), action.action_id, now, SOURCES, identity=identity()
    )


async def test_parent_and_children_use_disjoint_actual_cost_holds(
    governed_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, directory = await prepare(governed_factory)
    child = UUID(int=11)
    await directory.register_work(work(child, parent=TASK, amount="0.40"), control())
    child_action = await pending(journal, task=child, amount="0.40")
    assert (await authorize(journal, child_action)).state == ActionState.AUTHORIZED
    parent_over = await pending(journal, key=101, amount="0.600001")
    with pytest.raises(ValueError):
        await authorize(journal, parent_over)
    parent_exact = await pending(journal, key=102, amount="0.60")
    await authorize(journal, parent_exact)
    assert (await journal.budget(scope(), NOW)).daily_held_usd == Decimal("1.00")
    child_over = await pending(journal, key=103, task=child, amount="0.000001")
    with pytest.raises(ValueError):
        await authorize(journal, child_over, now=NOW + timedelta(minutes=2))
    assert (await journal.get_action(scope(child), child_over.action_id)).consumed_at is None


@pytest.mark.parametrize("actual", [None, Decimal("0.30")])
async def test_prior_unknown_or_spent_parent_funds_cannot_be_redelegated(
    governed_factory: async_sessionmaker[AsyncSession],
    actual: Decimal | None,
) -> None:
    journal, directory = await prepare(governed_factory)
    original = await pending(journal, amount="0.30")
    await authorize(journal, original)
    await journal.reconcile(scope(), original.action_id, actual)
    child = UUID(int=11)
    with pytest.raises(DirectoryDeniedError):
        await directory.register_work(work(child, parent=TASK, amount="0.700001"), control())
    await directory.register_work(work(child, parent=TASK, amount="0.70"), control())
    await authorize(journal, await pending(journal, key=101, task=child, amount="0.70"))
    with pytest.raises(ValueError):
        await authorize(journal, await pending(journal, key=102, amount="0.000001"))


async def test_registered_duplicate_consumers_reserve_and_consume_only_once(
    governed_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, _ = await prepare(governed_factory)
    action = await pending(journal)
    results = await asyncio.gather(
        authorize(journal, action), authorize(journal, action), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert (await journal.budget(scope(), NOW)).work_held_usd == Decimal("0.40")


@pytest.mark.parametrize(
    "revocation",
    [
        "member",
        "principal",
        "viewer",
        "owner",
        "work",
        "parent",
        "pause",
        "company",
        "workspace",
        "grant",
    ],
)
async def test_current_revocation_blocks_exact_old_approval_without_consumption(
    governed_factory: async_sessionmaker[AsyncSession],
    revocation: str,
) -> None:
    journal, directory = await prepare(governed_factory)
    await directory.register_work(work(CHILD, parent=TASK, amount="0.50"), control())
    action = await pending(journal, task=CHILD)
    if revocation in {"member", "principal", "viewer", "owner"}:
        await directory.set_membership(
            MembershipChange(
                company_id=COMPANY,
                principal_id=OWNER if revocation == "owner" else ACTOR,
                role={"owner": "owner", "viewer": "viewer"}.get(revocation, "member"),
                principal_active=revocation != "principal",
                membership_active=revocation not in {"member", "owner"},
            ),
            control(),
        )
    elif revocation in {"work", "parent"}:
        await directory.set_work_active(
            control(), task_id=CHILD if revocation == "work" else TASK, active=False
        )
    elif revocation == "pause":
        await journal.set_paused(scope(principal=OWNER), True)
    else:
        async with governed_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            if revocation == "grant":
                await session.execute(
                    update(WorkPrincipal)
                    .where(
                        WorkPrincipal.company_id == COMPANY,
                        WorkPrincipal.task_id == CHILD,
                        WorkPrincipal.principal_id == ACTOR,
                    )
                    .values(principal_id=OWNER)
                )
            else:
                column = "company_active" if revocation == "company" else "workspace_active"
                await session.execute(
                    update(DirectoryCompany)
                    .where(DirectoryCompany.company_id == COMPANY)
                    .values(**{column: False})
                )
    with pytest.raises(ValueError):
        await authorize(journal, action)
    assert (await journal.get_action(scope(CHILD), action.action_id)).consumed_at is None
    async with governed_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (await session.scalars(select(CostHold))).all() == []


@pytest.mark.parametrize(
    "mismatch",
    [
        "trace",
        "actor",
        "workspace",
        "identity",
        "company",
        "source",
        "expiry",
        "price",
        "missing_work",
        "cap",
    ],
)
async def test_scope_source_and_current_versions_are_revalidated_inside_authorization(
    governed_factory: async_sessionmaker[AsyncSession],
    mismatch: str,
) -> None:
    journal, _ = await prepare(governed_factory)
    action = await pending(journal, task=UUID(int=19) if mismatch == "missing_work" else TASK)
    current_scope, current_identity, current_sources, now = (
        scope(action.task_id),
        identity(),
        SOURCES,
        NOW,
    )
    if mismatch == "trace":
        current_scope = current_scope.model_copy(update={"trace_id": UUID(int=99)})
    if mismatch == "actor":
        current_scope, current_identity = scope(principal=OWNER), identity(OWNER)
    if mismatch == "workspace":
        current_identity = identity(workspace=UUID(int=99))
    if mismatch == "identity":
        current_identity = identity(OWNER)
    if mismatch == "company":
        current_scope = current_scope.model_copy(update={"company_id": UUID(int=99)})
    if mismatch == "source":
        current_sources = (ResourceRevision(resource="fixture:stockflow", revision="changed"),)
    if mismatch == "expiry":
        now += timedelta(hours=24)
    if mismatch in {"price", "cap"}:
        async with governed_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(
                update(CompanyControl)
                .where(CompanyControl.company_id == COMPANY)
                .values(
                    **(
                        {"price_version": "prices-2"}
                        if mismatch == "price"
                        else {"work_cap_usd": Decimal("0.20")}
                    )
                )
            )
    with pytest.raises(ValueError):
        await journal.authorize_registered(
            current_scope, action.action_id, now, current_sources, identity=current_identity
        )
    assert (await journal.get_action(scope(action.task_id), action.action_id)).consumed_at is None


async def test_registered_owner_decision_preserves_actor_and_cannot_renew_expiry(
    governed_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, _ = await prepare(governed_factory)
    action = await pending(journal, decision=False)
    first = await journal.approve_registered(
        scope(principal=OWNER), action.action_id, action_hash(action), NOW, identity=identity(OWNER)
    )
    again = await journal.approve_registered(
        scope(principal=OWNER),
        action.action_id,
        action_hash(action),
        NOW + timedelta(minutes=1),
        identity=identity(OWNER),
    )
    assert first.approval == again.approval and first.proposal.actor_id == ACTOR
    assert first.approval is not None and first.approval.approver_id == OWNER
    await authorize(journal, action)


@pytest.mark.parametrize("invalid", ["actor", "owner", "work", "caller", "workspace", "price"])
async def test_owner_decision_rechecks_current_authority_before_committing(
    governed_factory: async_sessionmaker[AsyncSession],
    invalid: str,
) -> None:
    journal, directory = await prepare(governed_factory)
    action = await pending(journal, decision=False)
    approval_scope, approval_identity = scope(principal=OWNER), identity(OWNER)
    if invalid in {"actor", "owner"}:
        await directory.set_membership(
            MembershipChange(
                company_id=COMPANY,
                principal_id=ACTOR if invalid == "actor" else OWNER,
                role="member" if invalid == "actor" else "owner",
                membership_active=False,
            ),
            control(),
        )
    elif invalid == "work":
        await directory.set_work_active(control(), task_id=TASK, active=False)
    elif invalid == "caller":
        approval_scope, approval_identity = scope(), identity()
    elif invalid == "workspace":
        approval_identity = identity(OWNER, UUID(int=99))
    else:
        async with governed_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(
                update(CompanyControl)
                .where(CompanyControl.company_id == COMPANY)
                .values(price_version="new-prices")
            )
    with pytest.raises(ValueError):
        await journal.approve_registered(
            approval_scope, action.action_id, action_hash(action), NOW, identity=approval_identity
        )
    assert (await journal.get_action(scope(), action.action_id)).approval is None


async def test_imported_action_trace_mismatch_cannot_use_a_valid_registered_scope(
    governed_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, _ = await prepare(governed_factory)
    action = await pending(journal)
    bad = ActionProposal.model_validate(
        action.model_dump() | {"action_id": UUID(int=101), "trace_id": UUID(int=99)}
    )
    forged = scope().model_copy(update={"trace_id": UUID(int=99)})
    await journal.submit(bad, forged)
    await journal.approve(scope(principal=OWNER), bad.action_id, action_hash(bad), NOW)
    with pytest.raises(ValueError):
        await journal.authorize_registered(
            scope(), bad.action_id, NOW, SOURCES, identity=identity()
        )
