"""An actual approval/hold is insufficient for a wrong immutable draft or signer."""

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.execution.runtime_models import EffectIntent
from nexus.tests.integration.test_company_directory import ACTOR, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def test_wrong_pinned_hash_with_actual_approval_rolls_back_no_request(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(
        dispatch_factory, draft.model_copy(update={"payload_sha256": "f" * 64})
    )
    calls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200)

    config = NotificationTransportConfiguration(
        enabled=True,
        api_key=SecretStr("fixture-only"),
        http_transport=httpx.MockTransport(response),
    )
    service = NotificationDispatchStore(
        dispatch_factory, drafts, effects, target, "owner.notifications", configuration=config
    )
    with pytest.raises(ValueError):
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


async def test_actual_nonowner_signer_cannot_borrow_owner_lease(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    drafts, case, _ = await configured_notifications(dispatch_factory, tmp_path)
    await accept_report(dispatch_factory, case)
    event = await acceptance_event(dispatch_factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    lease, action, effects, target = await actual_sender(dispatch_factory, draft)
    service = NotificationDispatchStore(
        dispatch_factory,
        drafts,
        effects,
        target,
        "owner.notifications",
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("fixture-only"),
            http_transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        ),
    )
    with pytest.raises(ValueError):
        await service.dispatch(lease, identity(ACTOR), draft.draft_id, action.action_id)
