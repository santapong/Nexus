"""Draft/link/cursor share one real company transaction; no nested or partial acknowledgement."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.event_models import BrainEventCursor
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import DecisionSelector, DigestSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.qualified_consumer import QualifiedNotificationConsumer
from nexus.company.notifications.qualified_contracts import DraftPublication
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import configured_qualified


async def test_actual_native_batch_publishes_links_and_cursor_once_without_m1_mutation(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    emitter = NativeFactEmitter(facts_factory, store.loader.reader)
    first = await emitter.emit(
        owner_scope(),
        identity(OWNER),
        DecisionSelector(company_id=COMPANY, action_id=pending.action.proposal.action_id),
    )
    assert first is not None
    second = await emitter.emit(
        owner_scope(),
        identity(OWNER),
        DigestSelector(company_id=COMPANY, schedule="qualified-weekly-v1"),
    )
    if second is None:
        pytest.skip("Actual current weekly bucket is not yet due")
    before = await saved_m1(facts_factory)
    consumer = QualifiedNotificationConsumer(
        store, consumer="qualified-owner-v1", recipe_version="qualified-v1"
    )
    result = await consumer.consume(control(), identity(OWNER))
    published = tuple(row for row in result.publications if row.state == "published")
    assert {row.event_id for row in published} == {first.event_id, second.event_id}
    assert result.cursor.last_sequence == second.sequence
    assert (await consumer.consume(control(), identity(OWNER))).publications == ()
    async with facts_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(NotificationDraftRow)) == 2
        assert await session.scalar(select(func.count()).select_from(NotificationEventLinkRow)) == 2
    assert await saved_m1(facts_factory) == before


async def test_second_actionable_source_failure_rolls_back_first_draft_link_and_cursor(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    pending = await case.preparation.prepare_author(profile.reference)
    emitter = NativeFactEmitter(facts_factory, store.loader.reader)
    assert await emitter.emit(
        owner_scope(),
        identity(OWNER),
        DecisionSelector(company_id=COMPANY, action_id=pending.action.proposal.action_id),
    )
    if not await emitter.emit(
        owner_scope(),
        identity(OWNER),
        DigestSelector(company_id=COMPANY, schedule="qualified-weekly-v1"),
    ):
        pytest.skip("Actual weekly bucket not yet due")
    from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore

    original = QualifiedNotificationDraftStore.publish_locked
    reached = 0

    async def fail_second(
        self: QualifiedNotificationDraftStore,
        session: AsyncSession,
        cc: CompanyControl,
        scope: CompanyControlScope,
        signed: VerifiedIdentity,
        event: OutboxEvent,
        recipient: OwnerRecipientPolicy,
    ) -> DraftPublication:
        nonlocal reached
        reached += 1
        if reached == 2:
            raise NotificationUnavailableError("Private actionable source is unavailable")
        return await original(self, session, cc, scope, signed, event, recipient)

    monkeypatch.setattr(QualifiedNotificationDraftStore, "publish_locked", fail_second)
    before = await saved_m1(facts_factory)
    with pytest.raises(NotificationUnavailableError):
        await QualifiedNotificationConsumer(
            store, consumer="atomic-failure-v1", recipe_version="qualified-v1"
        ).consume(control(), identity(OWNER))
    assert reached == 2
    async with facts_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        for table in (NotificationDraftRow, NotificationEventLinkRow, BrainEventCursor):
            assert not await session.scalar(select(func.count()).select_from(table))
    assert await saved_m1(facts_factory) == before
