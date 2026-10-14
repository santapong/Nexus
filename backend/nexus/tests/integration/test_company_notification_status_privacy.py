"""Provider lookup returns no status after actual source revocation during byte I/O."""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.status_store import NotificationStatusStore
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_source_revoke_during_real_mock_get_denies_no_delivery_record(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    calls: list[str] = []

    async def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"id": str(UUID(int=8110))})
        await owner_source(dispatch_factory, active=False)
        return httpx.Response(
            200,
            json={
                "object": "email",
                "id": str(UUID(int=8110)),
                "from": draft.payload.sender,
                "to": [draft.payload.recipient],
                "subject": draft.payload.subject,
                "text": draft.payload.text,
                "html": None,
                "cc": [],
                "bcc": [],
                "reply_to": [],
                "last_event": "delivered",
            },
        )

    config = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("fixture-only"),
        http_transport=httpx.MockTransport(response),
    )
    sender = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications", configuration=config
    )
    await sender.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    status = NotificationStatusStore(dispatch_factory, drafts, target=target, configuration=config)
    with pytest.raises(ValueError):
        await status.poll(control(), identity(OWNER), draft.draft_id)
    assert calls == ["POST", "GET"]
    record = await effects.get(lease, identity(OWNER), action.action_id)
    assert (
        record.state == "succeeded"
        and record.receipt is not None
        and record.receipt.external_id == str(UUID(int=8110))
    )
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NotificationObservationRow)
                .where(NotificationObservationRow.observation_kind == "delivery")
            )
            == 0
        )
