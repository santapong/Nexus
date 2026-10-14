"""Actual FK, SQL NULL, forced tenant isolation and immutable normal014 histories."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.notifications.notification_models import (
    NotificationDraftRow,
    NotificationEventLinkRow,
)
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.native_profile_support import configured_profile
from nexus.tests.notification_schema_support import draft_row, persist_schema_draft
from nexus.tests.notification_schema_support import (
    notification_schema_factory as notification_schema_factory,
)


async def test_notification_drafts_are_forced_scoped_immutable_and_indexed(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_profile(notification_schema_factory, tmp_path)
    row = await persist_schema_draft(
        notification_schema_factory, case.payload.children[0].binding.task_id
    )
    async with notification_schema_factory() as session, session.begin():
        assert (await session.scalars(select(NotificationDraftRow))).all() == []
    for statement in (
        update(NotificationDraftRow).values(template_version="rewritten"),
        delete(NotificationDraftRow),
    ):
        with pytest.raises(DBAPIError, match="Management history is immutable"):
            async with notification_schema_factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                await session.execute(statement)
    async with notification_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        flags = (
            await session.execute(
                text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid='company_notification_drafts'::regclass"
                )
            )
        ).one()
        assert flags == (True, True)
        await session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = await session.execute(
            text(
                "EXPLAIN SELECT draft_id FROM company_notification_drafts "
                "WHERE company_id=:company AND recipient_owner_id=:owner "
                "ORDER BY recorded_at,draft_id"
            ),
            {"company": COMPANY, "owner": row.recipient_owner_id},
        )
        assert "ix_notification_draft_owner" in "\n".join(str(item[0]) for item in plan)


@pytest.mark.parametrize("failure", ["foreign", "owner", "digest_null", "routine_due"])
async def test_restricted_draft_scope_owner_and_null_schedule_shape_reject(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    case = await configured_profile(notification_schema_factory, tmp_path)
    row = draft_row(case.payload.children[0].binding.task_id)
    if failure == "foreign":
        row.company_id = uuid4()
    elif failure == "owner":
        row.recipient_owner_id = uuid4()
    elif failure == "digest_null":
        row.kind, row.subject_kind = "daily", "digest_report"
    else:
        row.due_bucket = "unexpected"
    with pytest.raises(DBAPIError):
        async with notification_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(row)
            await session.flush()


async def test_event_link_native_sequence_cannot_be_spliced_and_event_replay_is_unique(
    notification_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_profile(notification_schema_factory, tmp_path)
    row = await persist_schema_draft(
        notification_schema_factory, case.payload.children[0].binding.task_id
    )
    async with notification_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        event = await session.scalar(select(BrainEvent).order_by(BrainEvent.sequence).limit(1))
        assert event is not None
        event_id, sequence = event.event_id, event.sequence
    with pytest.raises(DBAPIError, match="fk_notification_link_event"):
        async with notification_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(
                NotificationEventLinkRow(
                    company_id=COMPANY,
                    event_id=event_id,
                    event_sequence=sequence + 1,
                    draft_id=row.draft_id,
                )
            )
    async with notification_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            NotificationEventLinkRow(
                company_id=COMPANY,
                event_id=event_id,
                event_sequence=sequence,
                draft_id=row.draft_id,
            )
        )
    with pytest.raises(DBAPIError):
        async with notification_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(
                NotificationEventLinkRow(
                    company_id=COMPANY,
                    event_id=event_id,
                    event_sequence=sequence,
                    draft_id=row.draft_id,
                )
            )
