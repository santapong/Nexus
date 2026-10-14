"""Current owner/page/source visibility and explicit old/new dispositions, without sending."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.native_fact_contracts import BlockedSelector, CapSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.control_store import CompanyControls
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.qualified_consumer import QualifiedNotificationConsumer
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_effects import fixture_receipt, issued_fixture_action
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import configured_qualified, pending_event


async def test_own_cap_unknown_billing_and_paused_work_are_explicit_native_routine_drafts(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    action, lease = await issued_fixture_action(facts_factory, case)
    await case.native.effects.record_receipt(
        lease, identity(action.actor_id), fixture_receipt(action), actual_usd=None
    )
    emitter = NativeFactEmitter(facts_factory, store.loader.reader)
    cap = await emitter.emit(
        owner_scope(), identity(OWNER), CapSelector(company_id=COMPANY, task_id=action.task_id)
    )
    assert cap is not None
    held = await store.publish_event(control(), identity(OWNER), cap.event_id)
    assert held.kind == "routine" and "Billing: unknown" in held.payload.text
    await CompanyControls(facts_factory).set_paused_registered(control(), identity(OWNER), True)
    blocked = await emitter.emit(
        owner_scope(), identity(OWNER), BlockedSelector(company_id=COMPANY, task_id=action.task_id)
    )
    assert blocked is not None
    draft = await store.publish_event(control(), identity(OWNER), blocked.event_id)
    assert (
        "company_paused" in draft.payload.text
        and "No explicit owner cancellation" in draft.payload.text
    )


async def test_current_batch_source_loss_hides_already_collected_body_and_never_acks_disabled(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    event = await pending_event(facts_factory, store, case)
    draft = await store.publish_event(control(), identity(OWNER), event.event_id)
    async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
        session,
        cc,
        _,
    ):
        assert (
            await store.get_current_locked(session, cc, control(), identity(OWNER), draft.draft_id)
            == draft
        )
        await store.qualify_current_batch_locked(session, cc, control(), identity(OWNER), (draft,))
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
    before = await saved_m1(facts_factory)
    with pytest.raises(ValueError):
        await store.get_current(control(), identity(OWNER), draft.draft_id)
    with pytest.raises(ValueError):
        await QualifiedNotificationConsumer(
            store, consumer="private-v1", recipe_version="qualified-v1"
        ).consume(control(), identity(OWNER))
    store.policy = store.policy.model_copy(update={"enabled": False})
    with pytest.raises(ValueError, match="disabled"):
        await QualifiedNotificationConsumer(
            store, consumer="disabled-v1", recipe_version="qualified-v1"
        ).consume(control(), identity(OWNER))
    assert await saved_m1(facts_factory) == before


async def test_actual_owner_decision_makes_prior_wake_explicitly_obsolete_with_no_body(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    event = await pending_event(facts_factory, store, case)
    from datetime import UTC, datetime

    from nexus.harness.canonical import action_hash
    from nexus.harness.journal import CompanyJournal
    from nexus.harness.journal_models import JournalAction
    from nexus.tests.generated_artifact_fixture import ledger

    async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        row = await session.get(JournalAction, event.action_id)
        assert row is not None
        from nexus.company.contracts.actions import ActionProposal

        proposal = ActionProposal.model_validate_json(row.proposal_json)
    await CompanyJournal(facts_factory).approve_registered(
        ledger(case.payload.children[0].binding).model_copy(update={"principal_id": OWNER}),
        proposal.action_id,
        action_hash(proposal),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    before = await saved_m1(facts_factory)
    result = await QualifiedNotificationConsumer(
        store, consumer="obsolete-v1", recipe_version="qualified-v1"
    ).consume(control(), identity(OWNER))
    obsolete = tuple(row for row in result.publications if row.event_id == event.event_id)
    assert len(obsolete) == 1 and obsolete[0].state == "obsolete" and obsolete[0].draft is None
    assert result.cursor.last_sequence == event.sequence
    assert await saved_m1(facts_factory) == before
