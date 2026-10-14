"""Actual M1 atomic owner slot/receipt with explicit offline HTTP transport only."""

from pathlib import Path
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_actual_new_permit_once_and_known_replay_never_posts(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    saved = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, saved)
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": str(UUID(int=8100))})

    service = NotificationDispatchStore(
        dispatch_factory,
        drafts,
        effects,
        target,
        "owner.notifications",
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("fixture-only"),
            http_transport=httpx.MockTransport(response),
        ),
    )
    result = await service.dispatch(lease, identity(OWNER), saved.draft_id, action.action_id)
    assert (
        result is not None and result.outcome == "accepted" and result.delivery_state == "unknown"
    )
    assert len(calls) == 1
    assert await service.dispatch(lease, identity(OWNER), saved.draft_id, action.action_id) is None
    assert len(calls) == 1 and calls[0].content == saved.payload.wire_bytes()
    record = await effects.get(lease, identity(OWNER), action.action_id)
    assert record.receipt is not None and record.receipt.external_id == str(UUID(int=8100))
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.scalar(select(func.count()).select_from(NotificationDispatchRow)) == 1
