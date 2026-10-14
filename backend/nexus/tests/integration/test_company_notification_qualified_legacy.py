"""New adapter/persistence retain old actual failed and independent accepted draft behavior."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import read_event
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationPolicy, OwnerRecipientPolicy
from nexus.company.notifications.native_facts import render_native_draft
from nexus.company.notifications.qualified_render import render_qualified_draft
from nexus.company.notifications.recipient_registry import (
    FileOwnerRecipients,
    RecipientRegistryFile,
)
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_fact_effects import fixture_receipt, issued_fixture_action
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import configured_qualified


async def test_actual_failed_old_loader_and_renderer_are_byte_identical_through_new_adapter(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, path = await configured_qualified(facts_factory, tmp_path)
    action, lease = await issued_fixture_action(facts_factory, case)
    receipt = fixture_receipt(action)
    await case.native.effects.record_receipt(
        lease, identity(action.actor_id), receipt, actual_usd=None
    )
    async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
        session,
        cc,
        _,
    ):
        from nexus.company.notifications.draft_store import owner_scope

        row = await session.scalar(select(BrainEvent).where(BrainEvent.kind == "receipt_recorded"))
        assert row is not None
        event = await read_event(session, COMPANY, row.event_id)
        assert event is not None
        scope = owner_scope(control(), identity(OWNER))
        old = await store.loader.legacy.load(session, cc, scope, identity(OWNER), event)
        new = await store.loader.load(session, cc, scope, identity(OWNER), event)
        assert old == new and old.model_dump_json() == new.model_dump_json()
        recipient = RecipientRegistryFile.model_validate_json(path.read_bytes()).policies[0]
        now = datetime.now(UTC)
        first = render_native_draft(control(), store.policy, recipient, old, now)
        second = render_qualified_draft(control(), store.policy, recipient, new, now)
        assert first.model_dump_json() == second.model_dump_json()
    saved = await store.publish_event(control(), identity(OWNER), event.event_id)
    assert saved.kind == "routine" and saved.signal.kind == "failed"
    assert await store.get_current(control(), identity(OWNER), saved.draft_id) == saved


async def test_old_actual_protected_acceptance_draft_still_publishes_with_current_proof(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from nexus.company.notifications.draft_store import NotificationDraftStore
    from nexus.company.notifications.native_loader import NativeNotificationFactLoader
    from nexus.tests.integration.management_acceptance_fixture import issue_accepted_report_fixture

    scenario, accepted = await issue_accepted_report_fixture(facts_factory, tmp_path)
    now = datetime.now(UTC)
    path = tmp_path / "synthetic-old-accepted-owner.json"
    recipient = OwnerRecipientPolicy(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_id=OWNER,
        version="qualified-legacy.v1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    path.write_text(RecipientRegistryFile(policies=(recipient,)).model_dump_json())
    path.chmod(0o600)
    loader = NativeNotificationFactLoader(
        scenario.plans.catalog, scenario.artifacts, scenario.freshness
    )
    store = NotificationDraftStore(
        facts_factory,
        loader,
        FileOwnerRecipients(path),
        policy=NotificationPolicy(
            enabled=True, major_completion_task_ids=(accepted.target.author.task_id,)
        ),
    )
    async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        row = await session.scalar(
            select(BrainEvent).where(BrainEvent.kind == "verification_recorded")
        )
        assert row is not None
        event_id = row.event_id
    saved = await store.publish_event(control(), identity(OWNER), event_id)
    assert saved.signal.acceptance is not None and saved.signal.acceptance.acceptance == accepted
    assert await store.publish_event(control(), identity(OWNER), event_id) == saved
