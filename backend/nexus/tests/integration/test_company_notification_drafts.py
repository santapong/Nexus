"""Actual old-profile acceptance wake→owner draft; no native dispatch or email claim."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.recipient_registry import (
    RecipientConfigurationError,
    RecipientRegistryFile,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_native_support import configured_notifications, notifications_factory

__all__ = ["notifications_factory"]


async def acceptance_event(factory: async_sessionmaker[AsyncSession]) -> BrainEvent:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        row = await session.scalar(
            select(BrainEvent).where(
                BrainEvent.company_id == COMPANY, BrainEvent.kind == "verification_recorded"
            )
        )
        assert row is not None
        return row


async def test_real_independent_acceptance_draft_coalesces_without_cost_or_work_mutation(
    notifications_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_notifications(notifications_factory, tmp_path)
    accepted = await accept_report(notifications_factory, case)
    event = await acceptance_event(notifications_factory)
    saved = await store.publish_event(control(), identity(OWNER), event.event_id)
    assert saved.signal.acceptance is not None
    assert saved.signal.acceptance.acceptance == accepted
    assert "Independent work acceptance" in saved.payload.subject
    assert "goal completed" not in saved.payload.text.lower()
    assert saved.signal.source_event.value == accepted.recorded_at.isoformat()
    assert await store.publish_event(control(), identity(OWNER), event.event_id) == saved
    assert await store.get_current(control(), identity(OWNER), saved.draft_id) == saved
    async with management_owner_transaction(notifications_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.scalar(select(func.count()).select_from(NotificationDraftRow)) == 1
        assert await session.scalar(select(func.count()).select_from(NotificationEventLinkRow)) == 1


async def test_actual_owner_required_recipient_policy_change_and_unsupported_real_event(
    notifications_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, path = await configured_notifications(notifications_factory, tmp_path)
    await accept_report(notifications_factory, case)
    event = await acceptance_event(notifications_factory)
    with pytest.raises(BrainDeniedError):
        await store.publish_event(control(), identity(ACTOR), event.event_id)
    saved = await store.publish_event(control(), identity(OWNER), event.event_id)
    old = RecipientRegistryFile.model_validate_json(path.read_bytes()).policies[0]
    changed = old.model_copy(
        update={"recipient": "changed@example.invalid", "version": "changed.v2"}
    )
    path.write_text(RecipientRegistryFile(policies=(changed,)).model_dump_json())
    with pytest.raises(RecipientConfigurationError):
        await store.get_current(control(), identity(OWNER), saved.draft_id)
    with pytest.raises(NotificationUnavailableError):
        await store.publish_event(control(), identity(OWNER), uuid4())
    async with management_owner_transaction(notifications_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        source_event = await session.scalar(
            select(BrainEvent.event_id)
            .where(BrainEvent.company_id == COMPANY, BrainEvent.kind == "source_revised")
            .limit(1)
        )
        assert source_event is not None
    with pytest.raises(NotificationUnavailableError):
        await store.publish_event(control(), identity(OWNER), source_event)
