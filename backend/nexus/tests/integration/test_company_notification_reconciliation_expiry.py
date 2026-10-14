"""Final known-receipt reconciliation cannot outlive its actual target READ grant."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import (
    ResourceAccessChange,
    ResourceGeneration,
    ResourceRef,
)
from nexus.company.brain.access_models import BrainResource
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.status_store import NotificationStatusStore
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_dispatch_support import actual_sender, dispatch_factory
from nexus.tests.notification_native_support import configured_notifications

__all__ = ["dispatch_factory"]


async def target_deadline(factory: async_sessionmaker[AsyncSession], target: ResourceRef) -> None:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        resource = await session.get(BrainResource, (COMPANY, target.resource_id))
        assert resource is not None
        generation = resource.acl_generation
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=target,
            principal_id=OWNER,
            active=True,
            expected_generation=generation,
            expires_at=datetime.now(UTC) + timedelta(seconds=8),
        ),
    )


async def test_target_expiry_after_reconciliation_target_lookup_rolls_back_observation(
    dispatch_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
            return httpx.Response(200, json={"id": str(UUID(int=8123))})
        return httpx.Response(
            200,
            json={
                "object": "email",
                "id": str(UUID(int=8123)),
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
    await target_deadline(dispatch_factory, target)
    original = status._target
    lookups = 0

    async def delayed(
        session: AsyncSession, scope: CompanyControlScope, actor: VerifiedIdentity
    ) -> tuple[ResourceGeneration, ...]:
        nonlocal lookups
        grants = await original(session, scope, actor)
        lookups += 1
        if lookups == 3:
            for _ in range(8):
                await session.execute(select(func.pg_sleep(1.1)))
        return grants

    monkeypatch.setattr(status, "_target", delayed)
    with pytest.raises(NotificationUnavailableError):
        await status.reconcile_known(control(), identity(OWNER), draft.draft_id)
    assert calls == ["POST", "GET"]
    async with management_owner_transaction(dispatch_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NotificationObservationRow)
                .where(NotificationObservationRow.observation_kind == "reconciliation")
            )
            == 0
        )
