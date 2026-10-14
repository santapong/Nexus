"""Actual approval expiry after M1 intent flush must deny before the mock provider call."""

from collections.abc import Sequence
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
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import EffectIntent
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_approval_expiry_crosses_actual_m1_flush_without_http(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(
        dispatch_factory,
        draft,
        approval_now=datetime.now(UTC) - timedelta(hours=24) + timedelta(seconds=3),
    )
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": "00000000-0000-0000-0000-000000008122"})

    config = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("fixture-only"),
        http_transport=httpx.MockTransport(response),
    )
    service = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications", configuration=config
    )
    original = AsyncSession.flush

    async def delayed(self: AsyncSession, objects: Sequence[object] | None = None) -> None:
        target_flush = any(
            isinstance(row, EffectIntent) and row.action_id == action.action_id for row in self.new
        )
        await original(self, objects)
        if target_flush:
            for _ in range(3):
                await self.execute(select(func.pg_sleep(1.1)))

    monkeypatch.setattr(AsyncSession, "flush", delayed)
    with pytest.raises(NotificationUnavailableError):
        await service.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    assert not calls, "Expired actual approval must not reach HTTP after the native intent flush"
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.get(EffectIntent, (lease.company_id, action.action_id)) is None
        assert (
            await session.get(NotificationDispatchRow, (lease.company_id, draft.draft_id)) is None
        )
