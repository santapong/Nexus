"""Source/recipient expiry during the actual last cursor flush cannot acknowledge private drafts."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.event_models import BrainEventCursor
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.qualified_consumer import QualifiedNotificationConsumer
from nexus.company.notifications.recipient_registry import RecipientRegistryFile
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.native_fact_fixture import facts_factory as facts_factory
from nexus.tests.qualified_notification_fixture import configured_qualified, pending_event


@pytest.mark.parametrize("deadline", ["source", "recipient"])
async def test_natural_deadline_at_final_cursor_flush_rolls_back_all_records(
    facts_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deadline: str,
) -> None:
    store, case, path = await configured_qualified(facts_factory, tmp_path)
    event = await pending_event(facts_factory, store, case)
    expiry = datetime.now(UTC) + timedelta(seconds=10)
    if deadline == "source":
        async with brain_transaction(facts_factory, owner_scope(), identity(OWNER), owner=True) as (
            session,
            _,
            _,
        ):
            resource = await session.get(BrainResource, (COMPANY, RESOURCE))
            assert resource is not None
            generation = resource.acl_generation
        await ResourceAccessStore(facts_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=OWNER,
                active=True,
                expires_at=expiry,
                expected_generation=generation,
            ),
        )
    else:
        recipient = RecipientRegistryFile.model_validate_json(path.read_bytes()).policies[0]
        path.write_text(
            RecipientRegistryFile(
                policies=(recipient.model_copy(update={"expires_at": expiry}),)
            ).model_dump_json()
        )
    original = AsyncSession.flush
    reached = False

    async def delayed_cursor_flush(
        session: AsyncSession, objects: Sequence[object] | None = None
    ) -> None:
        nonlocal reached
        cursor = any(
            isinstance(row, BrainEventCursor) and row.last_sequence >= event.sequence
            for row in (*session.new, *session.dirty)
        )
        await original(session, objects=objects)
        if cursor and not reached:
            assert datetime.now(UTC) < expiry
            reached = True
            await asyncio.sleep((expiry - datetime.now(UTC)).total_seconds() + 0.04)

    monkeypatch.setattr(AsyncSession, "flush", delayed_cursor_flush)
    before = await saved_m1(facts_factory)
    with pytest.raises(ValueError):
        await QualifiedNotificationConsumer(
            store, consumer="final-clock-v1", recipe_version="qualified-v1"
        ).consume(control(), identity(OWNER))
    assert reached and await saved_m1(facts_factory) == before
    async with facts_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        for table in (NotificationDraftRow, NotificationEventLinkRow, BrainEventCursor):
            assert not await session.scalar(select(func.count()).select_from(table))
