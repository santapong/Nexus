"""Exclusive native notification conformance; synthetic recipient/data, no provider calls."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.notifications.contracts import NotificationPolicy, OwnerRecipientPolicy
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.recipient_registry import (
    FileOwnerRecipients,
    RecipientRegistryFile,
)
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, migrate
from nexus.tests.metric_fixture import MetricScenario, configured_metric


@pytest.fixture
async def notifications_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notifications"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def configured_notifications(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[NotificationDraftStore, MetricScenario, Path]:
    case = await configured_metric(factory, root)
    now = datetime.now(UTC)
    path = root / "synthetic-notification-recipient.json"
    policy = OwnerRecipientPolicy(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_id=OWNER,
        version="conformance-only.v1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    path.write_text(RecipientRegistryFile(policies=(policy,)).model_dump_json())
    path.chmod(0o600)
    loader = NativeNotificationFactLoader(
        case.store.catalog, case.store.artifacts, case.store.freshness
    )
    store = NotificationDraftStore(
        factory,
        loader,
        FileOwnerRecipients(path),
        policy=NotificationPolicy(enabled=True, major_completion_task_ids=case.request.task_ids),
    )
    return store, case, path
