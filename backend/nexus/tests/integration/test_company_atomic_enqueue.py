"""Actual DBOS SQL enqueue commits together with exact approval consumption and cost hold."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from dbos import DBOS
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.work import WorkItem
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dbos_queue import (
    APPLICATION_VERSION,
    WORKFLOW_NAME,
    enqueue_authorized_segment,
)
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_store import ExecutionStore, next_segment_id
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.standing_journal import StandingJournal
from nexus.harness.standing_store import StandingAuthorityStore
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    TASK,
    TRACE,
    WORKSPACE,
    migrate,
)
from nexus.tests.integration.test_company_registered_authorization import (
    NOW,
    SOURCES,
    identity,
    prepare,
    scope,
)
from nexus.tests.integration.test_company_registered_authorization import (
    pending as pending_action,
)


@dataclass
class Databases:
    app: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]


@pytest.fixture
async def enqueue_database() -> AsyncIterator[Databases]:
    if not settings.company_test_database_url:
        pytest.skip("explicit private atomic-enqueue DB is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_enqueue"
    engine = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    await asyncio.to_thread(
        DBOS.migrate,
        url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        application_role="nexus_company_app",
    )
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield Databases(
            async_sessionmaker(app, expire_on_commit=False),
            async_sessionmaker(engine, expire_on_commit=False),
        )
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
            await connection.execute(text("DROP SCHEMA dbos CASCADE"))
        await engine.dispose()


def continuation(action_id: UUID, *, segment: int = 12) -> SegmentCommand:
    return SegmentCommand(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        workspace_id=WORKSPACE,
        run_id=UUID(int=11),
        action_id=action_id,
        segment_id=UUID(int=segment),
    )


async def pending(databases: Databases) -> tuple[CompanyJournal, SegmentCommand]:
    journal, _ = await prepare(databases.app)
    runtime = ExecutionStore(databases.app)
    registered = await runtime.register(
        ExecutionRegistration(
            work=WorkItem(
                company_id=COMPANY,
                task_id=TASK,
                trace_id=TRACE,
                goal_id=UUID(int=20),
                department="engineering",
                title="offline fixture",
                acceptance=("evidence",),
            ),
            run_id=UUID(int=11),
            workflow_name=WORKFLOW_NAME,
            workflow_version=APPLICATION_VERSION,
            model_profile="routine",
            model_registry_version="registry-1",
            quota=AttemptQuota(),
        ),
        scope(),
        identity(),
    )
    proposal = await pending_action(journal, key=13, decision=False)
    record = await journal.get_action(scope(), proposal.action_id)
    await journal.approve_registered(
        scope(principal=UUID(int=3)),
        proposal.action_id,
        record.proposal_hash,
        NOW,
        approved=True,
        identity=identity(UUID(int=3)),
    )
    return journal, continuation(proposal.action_id).model_copy(
        update={
            "segment_id": next_segment_id(registered),
        }
    )


async def count_workflows(databases: Databases) -> int:
    async with databases.admin() as session:
        return int(await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) or 0)


async def test_exact_approval_and_scheduling_are_committed_together(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    await journal.authorize_and_enqueue_registered(
        scope(), command, NOW, SOURCES, identity=identity()
    )
    assert await count_workflows(enqueue_database) == 1
    async with enqueue_database.admin() as session:
        row = await session.get(JournalAction, command.action_id)
        assert row and row.state == "authorized" and row.consumed_at
        assert await session.get(CostHold, command.action_id)


async def test_rejected_enqueue_rolls_back_approval_and_cost_hold(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    async with enqueue_database.admin() as session, session.begin():
        await session.execute(
            text(
                "DROP FUNCTION dbos.enqueue_workflow("
                "text,text,json[],json,text,text,text,text,bigint,bigint,text,"
                "integer,text,text,text,bigint,text)"
            )
        )
    with pytest.raises(DBAPIError):
        await journal.authorize_and_enqueue_registered(
            scope(), command, NOW, SOURCES, identity=identity()
        )
    assert await count_workflows(enqueue_database) == 0
    async with enqueue_database.admin() as session:
        row = await session.get(JournalAction, command.action_id)
        assert row and row.state == "awaiting_approval" and row.consumed_at is None
        assert await session.get(CostHold, command.action_id) is None


async def test_duplicate_payload_is_idempotent_but_changed_input_is_denied(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    await journal.authorize_and_enqueue_registered(
        scope(), command, NOW, SOURCES, identity=identity()
    )
    async with enqueue_database.app() as session, session.begin():
        await session.execute(
            select(text("set_config('nexus.company_id', :id, true)")).params(id=str(COMPANY))
        )
        assert await enqueue_authorized_segment(session, command, scope()) == command.workflow_id
        changed = command.model_copy(update={"workspace_id": UUID(int=99)})
        with pytest.raises(ValueError, match="binding"):
            await enqueue_authorized_segment(session, changed, scope())
    assert await count_workflows(enqueue_database) == 1


async def test_rolled_back_direct_enqueue_never_becomes_visible(
    enqueue_database: Databases,
) -> None:
    journal, command = await pending(enqueue_database)
    await journal.authorize_registered(
        scope(), command.action_id, NOW, SOURCES, identity=identity()
    )
    async with enqueue_database.app() as session:
        await session.execute(
            select(text("set_config('nexus.company_id', :id, true)")).params(id=str(COMPANY))
        )
        await enqueue_authorized_segment(session, command, scope())
        assert await count_workflows(enqueue_database) == 0
        await session.rollback()
    assert await count_workflows(enqueue_database) == 0


async def test_unapproved_command_cannot_schedule(enqueue_database: Databases) -> None:
    _, command = await pending(enqueue_database)
    async with enqueue_database.app() as session, session.begin():
        await session.execute(
            select(text("set_config('nexus.company_id', :id, true)")).params(id=str(COMPANY))
        )
        with pytest.raises(ValueError, match="authorized"):
            await enqueue_authorized_segment(session, command, scope())
    assert await count_workflows(enqueue_database) == 0


@pytest.mark.parametrize("field", ["run_id", "segment_id", "workspace_id"])
async def test_fresh_command_cannot_splice_unregistered_runtime_identity(
    enqueue_database: Databases,
    field: str,
) -> None:
    journal, command = await pending(enqueue_database)
    changed = command.model_copy(update={field: UUID(int=99)})
    with pytest.raises(ValueError, match=r"binding|workspace"):
        await journal.authorize_and_enqueue_registered(
            scope(), changed, NOW, SOURCES, identity=identity()
        )
    assert await count_workflows(enqueue_database) == 0
    record = await journal.get_action(scope(), command.action_id)
    assert record.consumed_at is None


async def test_standing_consumption_and_enqueue_roll_back_as_one_transaction(
    enqueue_database: Databases,
) -> None:
    from nexus.tests.integration.test_company_directory import control
    from nexus.tests.integration.test_company_standing_authority import authority, standing

    journal, command = await pending(enqueue_database)
    store = StandingAuthorityStore(enqueue_database.app)
    grant = standing().model_copy(
        update={
            "policy_version": "policy-1",
            "price_version": "prices-1",
            "issued_at": NOW,
            "expires_at": NOW + timedelta(hours=8),
        }
    )
    await store.bind_work(authority(), control(), identity(UUID(int=3)))
    await store.issue(grant, control(), identity(UUID(int=3)), NOW)
    original = (await journal.get_action(scope(), command.action_id)).proposal
    routine = original.model_copy(
        update={
            "action_id": UUID(int=14),
            "tool": "fake.internal.draft.v1",
            "tool_version": "v1",
            "resource": "fixture:report",
        }
    )
    await journal.submit(routine, scope())
    routine_command = command.model_copy(
        update={"action_id": routine.action_id, "run_id": UUID(int=99)}
    )
    combined = StandingJournal(enqueue_database.app)
    with pytest.raises(ValueError, match="binding"):
        await combined.authorize_and_enqueue_standing(
            scope(), routine_command, grant.grant_id, NOW, SOURCES, identity=identity()
        )
    assert (await combined.get_action(scope(), routine.action_id)).consumed_at is None
    assert (await combined.budget(scope(), NOW)).work_held_usd == 0
    valid = routine_command.model_copy(update={"run_id": command.run_id})
    assert (
        await combined.authorize_and_enqueue_standing(
            scope(), valid, grant.grant_id, NOW, SOURCES, identity=identity()
        )
        == valid.workflow_id
    )
    assert await count_workflows(enqueue_database) == 1
