"""Exclusive actual normal company profile for receipt-event transaction qualification."""

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
from nexus.tests.builder_runtime_support import BuilderScenario
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, migrate


@pytest.fixture
async def receipt_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_receipt_events"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
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


def draft_store(
    factory: async_sessionmaker[AsyncSession], item: BuilderScenario, root: Path
) -> NotificationDraftStore:
    """Current synthetic recipient config only; actual builder source/output references."""
    now = datetime.now(UTC)
    policy = OwnerRecipientPolicy(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_id=OWNER,
        version="receipt-conformance.v1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    path = root / "receipt-recipient.json"
    path.write_text(RecipientRegistryFile(policies=(policy,)).model_dump_json())
    path.chmod(0o600)
    return NotificationDraftStore(
        factory,
        NativeNotificationFactLoader(
            item.guard.catalog, item.guard.artifacts, item.guard.freshness
        ),
        FileOwnerRecipients(path),
        policy=NotificationPolicy(enabled=True),
    )
