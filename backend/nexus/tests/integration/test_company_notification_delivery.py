"""Known M1 provider identity permits bounded offline GET; unknown never retries or looks up."""

from pathlib import Path
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.status_store import NotificationStatusStore
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_known_acceptance_then_actual_message_delivery_observation_and_exact_coalescing(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"id": str(UUID(int=8101))})
        return httpx.Response(
            200,
            json={
                "object": "email",
                "id": str(UUID(int=8101)),
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
    result = await sender.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    assert result is not None and result.delivery_state == "unknown"
    before = await effects.get(lease, identity(OWNER), action.action_id)
    statuses = NotificationStatusStore(
        dispatch_factory, drafts, target=target, configuration=config
    )
    observed = await statuses.poll(control(), identity(OWNER), draft.draft_id)
    assert (
        observed is not None
        and observed.status is not None
        and observed.status.delivery_state == "delivered"
    )
    assert await statuses.poll(control(), identity(OWNER), draft.draft_id) == observed
    reconciled = await statuses.reconcile_known(control(), identity(OWNER), draft.draft_id)
    assert reconciled is not None and reconciled.kind == "reconciliation"
    assert reconciled.submission is not None and reconciled.submission.delivery_state == "unknown"
    assert calls == ["POST", "GET", "GET", "GET"]
    assert await effects.get(lease, identity(OWNER), action.action_id) == before


async def test_unknown_send_keeps_actual_hold_and_never_gets_or_posts_again(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ReadTimeout("private-fixture-detail", request=request)

    config = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("fixture-only"),
        http_transport=httpx.MockTransport(response),
    )
    sender = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications", configuration=config
    )
    result = await sender.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    assert result is not None and result.outcome == "unknown" and result.provider_id is None
    assert (await effects.get(lease, identity(OWNER), action.action_id)).state == "outcome_unknown"
    assert await sender.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id) is None
    statuses = NotificationStatusStore(
        dispatch_factory, drafts, target=target, configuration=config
    )
    assert await statuses.poll(control(), identity(OWNER), draft.draft_id) is None
    assert await statuses.reconcile_known(control(), identity(OWNER), draft.draft_id) is None
    assert calls == ["POST"]
