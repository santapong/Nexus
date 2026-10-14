"""Actual owner/current source facts create ID-only wakes without effects or state promotion."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import BlockedSelector, DecisionSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.control_store import CompanyControls
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import configured_facts
from nexus.tests.native_fact_fixture import facts_factory as facts_factory


async def test_pending_decision_coalesces_and_owner_decision_makes_old_wake_stale(
    facts_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    selector = DecisionSelector(company_id=COMPANY, action_id=pending.action.proposal.action_id)
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    before = await saved_m1(facts_factory)
    event = await emitter.emit(owner_scope(), identity(OWNER), selector)
    assert event is not None and event.kind == "decision_required"
    assert event.task_id == case.payload.children[0].binding.task_id
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) == event
    assert await saved_m1(facts_factory) == before
    # This test uses actual owner journal approval below; no HTTP configuration is required.
    from datetime import UTC, datetime

    from nexus.harness.canonical import action_hash
    from nexus.harness.journal import CompanyJournal
    from nexus.tests.generated_artifact_fixture import ledger

    await CompanyJournal(facts_factory).approve_registered(
        ledger(case.payload.children[0].binding).model_copy(update={"principal_id": OWNER}),
        selector.action_id,
        action_hash(pending.action.proposal),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) is None
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        assert (
            await emitter.reader.load_event_locked(
                session, cc, owner_scope(), identity(OWNER), event
            )
            is None
        )


async def test_pause_is_actual_blocked_state_without_execution_or_cancellation_inference(
    facts_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    services, case = await configured_facts(facts_factory, tmp_path)
    selector = BlockedSelector(company_id=COMPANY, task_id=case.payload.children[0].binding.task_id)
    emitter = NativeFactEmitter(facts_factory, NativeFactReader(services))
    assert await emitter.emit(owner_scope(), identity(OWNER), selector) is None
    before = await saved_m1(facts_factory)
    await CompanyControls(facts_factory).set_paused_registered(control(), identity(OWNER), True)
    event = await emitter.emit(owner_scope(), identity(OWNER), selector)
    assert event is not None
    async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
        session,
        cc,
        _,
    ):
        projection = await emitter.reader.load_event_locked(
            session, cc, owner_scope(), identity(OWNER), event
        )
        from nexus.company.brain.native_fact_contracts import BlockedState

        assert projection is not None and isinstance(projection.state, BlockedState)
        assert projection.state.eligibility.reason == "company_paused"
        assert projection.state.cancellation is None
        assert (
            projection.source_event.precision == "unknown" and projection.source_event.value is None
        )
    assert await saved_m1(facts_factory) == before
