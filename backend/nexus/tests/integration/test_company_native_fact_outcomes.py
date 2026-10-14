"""Real issued failure/unknown billing and native cap facts; candidates never imply completion."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.native_fact_contracts import (
    CapSelector,
    FailedReceiptSelector,
    WorkCapState,
)
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.contracts.results import VerificationResult
from nexus.company.management.canonical import canonical_sha256
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_plan_support import VERIFIER
from nexus.tests.native_fact_effects import fixture_receipt, issued_fixture_action
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_fact_fixture import facts_factory as facts_factory


async def test_actual_failed_receipt_wake_matches_production_hook_and_unknown_cap_keeps_hold(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    action, lease = await issued_fixture_action(facts_factory, case)
    receipt = fixture_receipt(action)
    await case.native.effects.record_receipt(
        lease, identity(action.actor_id), receipt, actual_usd=None
    )
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    selector = FailedReceiptSelector(company_id=COMPANY, action_id=action.action_id)
    before = await saved_m1(facts_factory)
    event = await emitter.emit(owner_scope(), identity(OWNER), selector)
    assert event is not None and event.resource.resource_id == RESOURCE and event.task_id is None
    assert (
        event.deduplication_key
        == f"native.receipt.failed.v1:{action.action_id}:{canonical_sha256(receipt)}"
    )
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) == event
    cap = await emitter.emit(
        owner_scope(), identity(OWNER), CapSelector(company_id=COMPANY, task_id=action.task_id)
    )
    assert cap is not None and cap.budget_day is None
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        fact = await emitter.reader.load_event_locked(
            session, cc, owner_scope(), identity(OWNER), event
        )
        assert (
            fact is not None
            and fact.state == receipt
            and fact.state_sha256 == canonical_sha256(receipt)
        )
        assert (
            fact.source_event.precision == "instant"
            and fact.source_event.value == receipt.recorded_at.isoformat()
        )
        budget = await emitter.reader.load_event_locked(
            session, cc, owner_scope(), identity(OWNER), cap
        )
        assert budget is not None and isinstance(budget.state, WorkCapState)
        assert (
            budget.state.billing_unknown
            and budget.state.held_usd == Decimal("0.2")
            and budget.state.spent_usd == 0
        )
        assert budget.state.delegated_usd == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "receipt_recorded")
            )
            == 1
        )
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.actual_usd is None and hold.state == "unknown"
    assert await saved_m1(facts_factory) == before


async def test_success_and_raw_passing_candidate_do_not_produce_failure_or_accepted_wake(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    action, lease = await issued_fixture_action(facts_factory, case)
    receipt = fixture_receipt(action, outcome="succeeded")
    await case.native.effects.record_receipt(
        lease, identity(action.actor_id), receipt, actual_usd=Decimal(0)
    )
    await case.native.effects.record_verification_candidate(
        lease,
        identity(action.actor_id),
        VerificationResult(
            company_id=COMPANY,
            verification_id=uuid4(),
            action_id=action.action_id,
            verifier_id=VERIFIER,
            verdict="pass",
            criterion_ids=case.payload.plan.items[0].acceptance,
            evidence_ids=(case.evidence_ids[0],),
        ),
    )
    before = await saved_m1(facts_factory)
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    assert (
        await emitter.emit(
            owner_scope(),
            identity(OWNER),
            FailedReceiptSelector(company_id=COMPANY, action_id=action.action_id),
        )
        is None
    )
    assert (
        await emitter.emit(
            owner_scope(), identity(OWNER), CapSelector(company_id=COMPANY, task_id=action.task_id)
        )
        is None
    )
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        _,
        _,
    ):
        assert not await session.scalar(
            select(func.count())
            .select_from(BrainEvent)
            .where(BrainEvent.kind.in_(("receipt_recorded", "verification_recorded")))
        )
    assert await saved_m1(facts_factory) == before
