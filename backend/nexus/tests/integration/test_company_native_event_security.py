"""Normal015 actual scoped FK/immutable/index gates; schema placeholders are rolled back."""

from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.native_event_records import read_event
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_native_event_schema import (
    native_schema_factory as native_schema_factory,
)
from nexus.tests.integration.test_company_native_event_schema import schema_event_values
from nexus.tests.native_profile_support import configured_profile


async def test_native_event_restricted_scope_immutability_and_full_fk_index(
    native_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_profile(native_schema_factory, tmp_path)
    async with native_schema_factory() as session:
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        values, _ = await schema_event_values(session, case)
        await session.execute(insert(cast(Table, BrainEvent.__table__)).values(**values))
        event = await read_event(session, COMPANY, cast(UUID, values["event_id"]))
        assert event is not None and event.task_id == case.payload.children[0].binding.task_id
        for statement in (
            update(BrainEvent)
            .where(BrainEvent.event_id == event.event_id)
            .values(kind="claims_changed"),
            text("DELETE FROM company_brain_events WHERE event_id=:event").bindparams(
                event=event.event_id
            ),
        ):
            with pytest.raises(DBAPIError, match="Brain history is immutable"):
                async with session.begin_nested():
                    await session.execute(statement)
        await session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = await session.execute(
            text(
                "EXPLAIN ANALYZE SELECT task_id FROM company_brain_events "
                "WHERE company_id=:company AND task_id=:task"
            ),
            {"company": COMPANY, "task": event.task_id},
        )
        plan_text = "\n".join(str(row[0]) for row in plan)
        (tmp_path / "native-event-explain.txt").write_text(plan_text)
        assert "Index" in plan_text and "task_id" in plan_text
        index = await session.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE "
                "tablename='company_brain_events' AND indexname='ix_brain_event_native_task'"
            )
        )
        assert isinstance(index, str) and "(company_id, task_id)" in index
        flags = (
            await session.execute(
                text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid='company_brain_events'::regclass"
                )
            )
        ).one()
        assert flags == (True, True)
        await session.execute(select(func.set_config("nexus.company_id", "", True)))
        assert (await session.scalars(select(BrainEvent))).all() == []
        # No synthetic wake commits; closing the session rolls this schema row back.


async def test_decision_event_action_cannot_be_spliced_to_another_registered_task(
    native_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_profile(native_schema_factory, tmp_path)
    from nexus.tests.integration.test_company_directory import OWNER, control
    from nexus.tests.integration.test_company_execution_store import identity

    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    prepared = await case.preparation.prepare_author(profile.reference)
    async with native_schema_factory() as session:
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        values, _ = await schema_event_values(session, case)
        values.update(kind="decision_required", action_id=prepared.action.proposal.action_id)
        await session.execute(insert(cast(Table, BrainEvent.__table__)).values(**values))
        with pytest.raises(DBAPIError, match="fk_brain_event_native_action_task"):
            async with session.begin_nested():
                values.update(
                    event_id=uuid4(),
                    sequence=10001,
                    deduplication_key="schema-wrong-task",
                    task_id=case.payload.children[1].binding.task_id,
                )
                await session.execute(insert(cast(Table, BrainEvent.__table__)).values(**values))
