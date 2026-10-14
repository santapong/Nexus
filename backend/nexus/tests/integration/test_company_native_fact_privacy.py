"""Current signed owner/resources/heads, persisted wake authenticity and permanent history."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.native_fact_contracts import BlockedSelector, BlockedState
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, SOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_fact_fixture import facts_factory as facts_factory


@pytest.mark.parametrize(
    "change", ["member", "signed_owner", "foreign", "resource", "source_unavailable"]
)
async def test_blocked_notification_privacy_rechecks_current_native_inputs(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    change: str,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    target = case.payload.children[0].binding
    await CompanyControls(facts_factory).set_paused_registered(control(), identity(OWNER), True)
    selector = BlockedSelector(company_id=COMPANY, task_id=target.task_id)
    scope, signed = owner_scope(), identity(OWNER)
    if change == "member":
        await PersistentCompanyDirectory(facts_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", principal_active=False
            ),
            control(),
        )
    elif change == "signed_owner":
        scope, signed = scope.model_copy(update={"principal_id": ACTOR}), identity(ACTOR)
    elif change == "foreign":
        selector = selector.model_copy(update={"company_id": uuid4()})
    elif change == "resource":
        async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
            session,
            _,
            _,
        ):
            resource = await session.get(BrainResource, (COMPANY, RESOURCE))
            assert resource is not None
            generation = resource.acl_generation
        await ResourceAccessStore(facts_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=OWNER,
                active=False,
                expected_generation=generation,
            ),
        )
    else:
        async with facts_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
            assert head is not None
            head.generation += 1
            head.availability = "unavailable"
    before = await saved_m1(facts_factory)
    with pytest.raises(ValueError):
        await NativeFactEmitter(facts_factory, NativeFactReader(services)).emit(
            scope, signed, selector
        )
    assert await saved_m1(facts_factory) == before


async def test_current_blocked_wake_retains_actual_ancestor_cancellation_and_rejects_forged_record(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    target = case.payload.children[0].binding
    await CompanyControls(facts_factory).set_paused_registered(control(), identity(OWNER), True)
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    selector = BlockedSelector(company_id=COMPANY, task_id=target.task_id)
    paused = await emitter.emit(owner_scope(), identity(OWNER), selector)
    assert paused is not None
    cancellation = await WorkCancellationStore(facts_factory).cancel(
        control(),
        identity(OWNER),
        CancellationCommand(
            company_id=COMPANY,
            target=case.payload.procedure.binding,
            reason="Permanent registered stop",
        ),
    )
    current = await emitter.emit(owner_scope(), identity(OWNER), selector)
    assert current is not None and current.event_id != paused.event_id
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) == current
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        assert (
            await emitter.reader.load_event_locked(
                session, cc, owner_scope(), identity(OWNER), paused
            )
            is None
        )
        fact = await emitter.reader.load_event_locked(
            session, cc, owner_scope(), identity(OWNER), current
        )
        assert fact is not None and isinstance(fact.state, BlockedState)
        inherited = fact.state.cancellation
        assert (
            inherited is not None and inherited.inherited and inherited.cancellation == cancellation
        )
        with pytest.raises(ValueError, match="record"):
            await emitter.reader.load_event_locked(
                session,
                cc,
                owner_scope(),
                identity(OWNER),
                current.model_copy(update={"native_snapshot_sha256": "f" * 64}),
            )


async def test_transient_company_control_cannot_invent_exhausted_native_cap(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    from nexus.company.brain.native_fact_contracts import CapSelector

    fake = CompanyControl(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_version="fixture-policy",
        price_version="fixture-prices",
        paused=False,
        daily_cap_usd=Decimal(0),
        work_cap_usd=Decimal(0),
    )
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        _,
        _,
    ):
        with pytest.raises(ValueError, match="actual locked"):
            await NativeFactReader(services).load_locked(
                session, fake, owner_scope(), identity(OWNER), CapSelector(company_id=COMPANY)
            )
    assert case.payload.company_id == COMPANY
