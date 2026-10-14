"""Exclusive normal015 real signed-owner inbox fixture; no sender/provider/UAT process."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from litestar import Litestar
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.notifications.api_services import NotificationApiServices
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.inbox_store import NotificationInboxStore
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import RecipientRegistryFile
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.qualified_notification_fixture import configured_qualified


@pytest.fixture
async def inbox_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notifications"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
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
                # Native015 production downgrade correctly refuses live native kinds.
                # Remove only this disposable owned fixture's events through admin teardown.
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class InboxCase:
    app: Litestar
    inbox: NotificationInboxStore
    drafts: tuple[NotificationDraft, ...]
    store: QualifiedNotificationDraftStore
    recipient_path: Path
    deadline: datetime | None


async def configured_inbox(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    *,
    mount: bool = True,
    enabled: bool = True,
    expiry: str | None = None,
    draft_count: int = 2,
) -> InboxCase:
    store, case, path = await configured_qualified(factory, root)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    first = await case.preparation.prepare_author(profile.reference)
    assert 1 <= draft_count <= 9
    second = first.action.proposal.model_copy(update={"action_id": uuid4()})
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=second.actor_id,
        task_id=second.task_id,
        trace_id=second.trace_id,
    )
    actions = [first.action.proposal]
    for _ in range(draft_count - 1):
        action = second.model_copy(update={"action_id": uuid4()})
        await CompanyJournal(factory).submit(action, scope)
        actions.append(action)
    deadline = datetime.now(UTC) + timedelta(seconds=20) if expiry else None
    if expiry == "source":
        await owner_source(factory, active=True, expires=deadline)
    elif expiry == "recipient":
        record = RecipientRegistryFile.model_validate_json(path.read_bytes())
        path.write_text(
            record.model_copy(
                update={
                    "policies": tuple(
                        policy.model_copy(update={"expires_at": deadline})
                        for policy in record.policies
                    )
                }
            ).model_dump_json()
        )
    emitter = NativeFactEmitter(factory, store.loader.reader)
    drafts = []
    for action in actions:
        event = await emitter.emit(
            owner_scope(),
            identity(OWNER),
            DecisionSelector(company_id=COMPANY, action_id=action.action_id),
        )
        assert event is not None
        drafts.append(await store.publish_event(control(), identity(OWNER), event.event_id))
    inbox = NotificationInboxStore(factory, store)
    directory = PersistentCompanyDirectory(factory)
    services = CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory))
    app = create_company_app(
        services,
        notification_services=NotificationApiServices(directory, inbox if enabled else None)
        if mount
        else None,
    )
    return InboxCase(app, inbox, tuple(drafts), store, path, deadline)
