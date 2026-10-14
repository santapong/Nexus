"""Read-only inbox separates recorded provider acceptance/delivery/unknown from work acceptance."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from litestar.testing import AsyncTestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.inbox_contracts import NotificationInboxEntry
from nexus.company.notifications.status_store import NotificationStatusStore
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_dispatch_support import actual_sender
from nexus.tests.notification_inbox_api_support import configured_inbox, inbox_factory

__all__ = ["inbox_factory"]
BASE = f"/api/v2/companies/{COMPANY}/notifications"


@pytest.mark.parametrize("provider", ["accepted_delivery", "unknown"])
async def test_actual_native_m1_observations_remain_separate_wire_facts(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path, provider: str
) -> None:
    # Sender setup is explicit public unmanaged M1 conformance only; this tests
    # inbox reads of genuine stored observations, not managed sender activation.
    case = await configured_inbox(inbox_factory, tmp_path)
    draft = case.drafts[0]
    lease, action, effects, target = await actual_sender(inbox_factory, draft)
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if provider == "unknown":
            raise httpx.ReadTimeout("fixture-only", request=request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": str(UUID(int=8490))})
        return httpx.Response(
            200,
            json={
                "object": "email",
                "id": str(UUID(int=8490)),
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
        inbox_factory, case.store, effects, target, "owner.notifications", configuration=config
    )
    assert await sender.dispatch(lease, identity(OWNER), draft.draft_id, action.action_id)
    if provider == "accepted_delivery":
        assert await NotificationStatusStore(
            inbox_factory, case.store, target=target, configuration=config
        ).poll(control(), identity(OWNER), draft.draft_id)
    before = tuple(calls)
    async with AsyncTestClient(case.app) as client:
        response_http = await client.get(f"{BASE}/{draft.draft_id}", headers=headers(OWNER))
        assert response_http.status_code == 200
        entry = NotificationInboxEntry.model_validate_json(response_http.content)
    assert tuple(calls) == before, "Inbox API must never GET or POST provider"
    assert entry.draft.signal.acceptance is None
    assert entry.latest_submission is not None and entry.latest_submission.submission is not None
    if provider == "accepted_delivery":
        assert entry.latest_submission.submission.outcome == "accepted"
        assert entry.latest_submission.submission.delivery_state == "unknown"
        assert entry.latest_delivery is not None and entry.latest_delivery.status is not None
        assert entry.latest_delivery.status.delivery_state == "delivered"
    else:
        assert entry.latest_submission.submission.outcome == "unknown"
        assert entry.latest_submission.submission.provider_id is None
        assert entry.latest_delivery is None and calls == ["POST"]
