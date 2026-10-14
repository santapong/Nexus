"""Actual final M1/source qualification denies offline transport after expiry."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.intent_check import NotificationIntentCheck
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_source_expiry_after_slot_flush_rolls_back_intent_slot_counter_no_http(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    await owner_source(
        dispatch_factory, active=True, expires=datetime.now(UTC) + timedelta(seconds=3)
    )
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": "00000000-0000-0000-0000-000000008102"})

    config = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("fixture-only"),
        http_transport=httpx.MockTransport(response),
    )
    service = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications", configuration=config
    )
    original = NotificationIntentCheck._slot

    async def slow(
        self: NotificationIntentCheck,
        session: AsyncSession,
        work: ExecutionWork,
        action_row: JournalAction,
        now: datetime,
    ) -> None:
        await original(self, session, work, action_row, now)
        await session.flush()
        await session.execute(select(func.pg_sleep(1.1)))
        await session.execute(select(func.pg_sleep(1.1)))
        await session.execute(select(func.pg_sleep(1.1)))

    monkeypatch.setattr(NotificationIntentCheck, "_slot", slow)
    with pytest.raises(NotificationUnavailableError):
        await service.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    assert not calls
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(EffectIntent, (lease.company_id, action.action_id)) is None
        assert (
            await session.get(NotificationDispatchRow, (lease.company_id, draft.draft_id)) is None
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ExecutionAttempt)
                .where(ExecutionAttempt.task_id == lease.task_id)
            )
            == 0
        )


async def test_defaultdisabled_leaves_actual_approved_action_unissued(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    service = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications"
    )
    with pytest.raises(NotificationUnavailableError):
        await service.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(EffectIntent, (lease.company_id, action.action_id)) is None
        assert (
            await session.get(NotificationDispatchRow, (lease.company_id, draft.draft_id)) is None
        )
