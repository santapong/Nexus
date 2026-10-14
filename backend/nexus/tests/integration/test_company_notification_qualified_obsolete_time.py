"""Skipped obsolete rows still contribute freshly captured resource expiry to the final barrier."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications import qualified_store
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.qualified_support import qualify_saved_inputs_locked
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import (
    configured_qualified,
    pending_event,
    resolve_event,
)


async def test_new_resource_deadline_crossing_after_obsolete_qualification_denies_visited_batch(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    event = await pending_event(facts_factory, store, case)
    draft = await store.publish_event(control(), identity(OWNER), event.event_id)
    await resolve_event(facts_factory, case, event)
    expiry = datetime.now(UTC) + timedelta(seconds=5)
    await owner_source(facts_factory, active=True, expires=expiry)
    original, calls = qualify_saved_inputs_locked, 0

    async def delayed_qualification(
        session: AsyncSession,
        cc: CompanyControl,
        scope: CompanyControlScope,
        signed: VerifiedIdentity,
        services: NativeFactServices,
        saved: NotificationDraft,
    ) -> tuple[datetime, ...]:
        nonlocal calls
        deadlines = await original(session, cc, scope, signed, services, saved)
        calls += 1
        if calls == 2:
            assert expiry in deadlines and datetime.now(UTC) < expiry
            await asyncio.sleep((expiry - datetime.now(UTC)).total_seconds() + 0.04)
        return deadlines

    monkeypatch.setattr(qualified_store, "qualify_saved_inputs_locked", delayed_qualification)
    with pytest.raises(ValueError, match="expired"):
        async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
            session,
            cc,
            _,
        ):
            await store.qualify_visited_batch_locked(
                session, cc, control(), identity(OWNER), (draft.draft_id,)
            )
    assert calls == 2
