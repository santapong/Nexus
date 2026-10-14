"""Company/day cap comes from five actual M1 holds, with no caller date or ancestor summation."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import CapSelector, CompanyCapState
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_contracts import WorkRegistration
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.transactions import management_owner_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, WORKSPACE, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_fact_fixture import facts_factory as facts_factory


async def test_company_cap_exact_current_bangkok_budget_without_fabricated_native_amount(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services, _ = await configured_facts(facts_factory, tmp_path)
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    selector = CapSelector(company_id=COMPANY)
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) is None
    for _ in range(5):
        await _hold_one(facts_factory)
    before = await saved_m1(facts_factory)
    event = await emitter.emit(owner_scope(), identity(OWNER), selector)
    assert (
        event is not None
        and event.task_id is None
        and event.budget_day == billing_day(datetime.now(UTC))
    )
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) == event
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        fact = await emitter.reader.load_event_locked(
            session, cc, owner_scope(), identity(OWNER), event
        )
        assert fact is not None and isinstance(fact.state, CompanyCapState)
        assert fact.state.cap_usd == fact.state.held_usd == Decimal(5)
        assert fact.state.spent_usd == 0 and not fact.state.billing_unknown
    assert await saved_m1(facts_factory) == before


async def _hold_one(factory: async_sessionmaker[AsyncSession]) -> None:
    task, trace = uuid4(), uuid4()
    owner = control().model_copy(update={"operation_id": uuid4()})
    async with management_owner_transaction(factory, owner, identity(OWNER)) as (session, _, _):
        await PersistentCompanyDirectory(factory).register_work_in_transaction(
            session,
            WorkRegistration(
                company_id=COMPANY,
                workspace_id=WORKSPACE,
                task_id=task,
                trace_id=trace,
                actor_id=ACTOR,
                allocation_usd=Decimal(1),
                allowed_principals=(ACTOR,),
            ),
            owner,
            identity(OWNER),
        )
    scope = LedgerScope(company_id=COMPANY, principal_id=ACTOR, task_id=task, trace_id=trace)
    action = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=task,
        trace_id=trace,
        actor_id=ACTOR,
        revision=1,
        tool="fake.internal.read.v1",
        tool_version="v1",
        resource="company.report",
        parameters={"operation": "hold-only-native-fixture"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal(1),
    )
    journal = CompanyJournal(factory)
    await journal.submit(action, scope)
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, action.action_id, datetime.now(UTC), (), identity=identity(ACTOR)
    )
