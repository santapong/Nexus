"""Real source revocation/final expiry roll back native drafts; no dispatch/provider involved."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import accept_report
from nexus.tests.notification_native_support import configured_notifications, notifications_factory

__all__ = ["notifications_factory"]


async def owner_source(
    factory: async_sessionmaker[AsyncSession], *, active: bool, expires: datetime | None = None
) -> None:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        generation = resource.acl_generation
    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=active,
            expected_generation=generation,
            expires_at=expires,
        ),
    )


async def test_current_owner_source_revoke_denies_stored_body_and_new_publication(
    notifications_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, case, _ = await configured_notifications(notifications_factory, tmp_path)
    await accept_report(notifications_factory, case)
    event = await acceptance_event(notifications_factory)
    saved = await store.publish_event(control(), identity(OWNER), event.event_id)
    await owner_source(notifications_factory, active=False)
    with pytest.raises(ValueError):
        await store.get_current(control(), identity(OWNER), saved.draft_id)
    with pytest.raises(ValueError):
        await store.publish_event(control(), identity(OWNER), event.event_id)


async def test_grant_expiry_after_actual_flush_rolls_back_draft_and_link(
    notifications_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, case, _ = await configured_notifications(notifications_factory, tmp_path)
    await accept_report(notifications_factory, case)
    event = await acceptance_event(notifications_factory)
    await owner_source(
        notifications_factory, active=True, expires=datetime.now(UTC) + timedelta(seconds=2)
    )
    original = store._persist

    async def delayed(
        session: AsyncSession, prepared: NotificationDraft, event_id: UUID
    ) -> NotificationDraft:
        saved = await original(session, prepared, event_id)
        await session.execute(select(func.pg_sleep(1.1)))
        await session.execute(select(func.pg_sleep(1.1)))
        return saved

    monkeypatch.setattr(store, "_persist", delayed)
    with pytest.raises(NotificationUnavailableError):
        await store.publish_event(control(), identity(OWNER), event.event_id)
    async with management_owner_transaction(notifications_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert await session.scalar(select(func.count()).select_from(NotificationDraftRow)) == 0
        assert await session.scalar(select(func.count()).select_from(NotificationEventLinkRow)) == 0
