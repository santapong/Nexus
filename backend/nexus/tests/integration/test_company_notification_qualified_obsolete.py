"""Resolved native decisions require complete licensing before body-free absence."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.qualified_consumer import QualifiedNotificationConsumer
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import (
    configured_qualified,
    pending_event,
    resolve_event,
)


async def test_current_resolved_decision_is_licensed_absence_and_batch_still_checks_sources(
    facts_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    event = await pending_event(facts_factory, store, case)
    draft = await store.publish_event(control(), identity(OWNER), event.event_id)
    await resolve_event(facts_factory, case, event)
    assert await store.get_current(control(), identity(OWNER), draft.draft_id) is None
    async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
        session,
        cc,
        _,
    ):
        await store.qualify_visited_batch_locked(
            session, cc, control(), identity(OWNER), (draft.draft_id,)
        )
    await owner_source(facts_factory, active=False)
    with pytest.raises(ValueError):
        await store.get_current(control(), identity(OWNER), draft.draft_id)
    with pytest.raises(ValueError):
        async with management_owner_transaction(facts_factory, control(), identity(OWNER)) as (
            session,
            cc,
            _,
        ):
            await store.qualify_visited_batch_locked(
                session, cc, control(), identity(OWNER), (draft.draft_id,)
            )


@pytest.mark.parametrize("published", [False, True])
async def test_resolved_event_source_loss_cannot_be_acknowledged_as_obsolete(
    facts_factory: async_sessionmaker[AsyncSession], tmp_path: Path, published: bool
) -> None:
    store, case, _ = await configured_qualified(facts_factory, tmp_path)
    event = await pending_event(facts_factory, store, case)
    if published:
        await store.publish_event(control(), identity(OWNER), event.event_id)
    await resolve_event(facts_factory, case, event)
    await owner_source(facts_factory, active=False)
    with pytest.raises(ValueError):
        await QualifiedNotificationConsumer(
            store, consumer="private-obsolete-v1", recipe_version="qualified-v1"
        ).consume(control(), identity(OWNER))
