"""Populated c005→c006 drain/invalidation preserves lifetime attempts and unknown billing."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Connection, MetaData, Table, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from nexus.company.contracts.work import WorkItem
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CostHold, JournalAction, WorkBudget
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, TASK, TRACE, WORKSPACE
from nexus.tests.integration.test_company_profile_migrations import profile_config
from nexus.tests.integration.test_company_registered_authorization import (
    NOW,
    SOURCES,
    identity,
    pending,
    prepare,
    scope,
)

RUN = UUID(int=700)
ACTION = UUID(int=100)


def setup_old(connection: Connection) -> None:
    command.upgrade(profile_config(connection), "company_005")
    connection.execute(text("GRANT USAGE ON SCHEMA public TO nexus_company_app"))
    connection.execute(
        text("GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
    )


def seed_old_lease(connection: Connection) -> None:
    old = Table("company_execution_work", MetaData(), autoload_with=connection)
    request = ExecutionRegistration(
        work=WorkItem(
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            goal_id=UUID(int=20),
            department="engineering",
            title="old injected run",
            acceptance=("checked",),
        ),
        run_id=RUN,
        workflow_name="fixture",
        workflow_version="fixture-v1",
        model_profile="routine",
        model_registry_version="registry-1",
        quota=AttemptQuota(),
    )
    values = {
        "company_id": COMPANY,
        "task_id": TASK,
        "trace_id": TRACE,
        "actor_id": ACTOR,
        "workspace_id": WORKSPACE,
        "parent_task_id": None,
        "run_id": RUN,
        "registration_json": request.model_dump_json(),
        "registration_hash": registration_digest(request),
        "workflow_name": "fixture",
        "workflow_version": "fixture-v1",
        "model_profile": "routine",
        "model_registry_version": "registry-1",
        "state": "running",
        "fence": 1,
        "worker_id": UUID(int=701),
        "lease_until": datetime.now(UTC) + timedelta(minutes=5),
        "lease_mode": "execute",
        "segment_number": 1,
        "segment_id": UUID(int=702),
        "waiting_action_id": None,
    }
    for name in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions"):
        values.update(
            {
                f"{name}_limit": getattr(request.quota, name),
                f"{name}_used": 1 if name == "tool_attempts" else 0,
                f"{name}_delegated": 0,
            }
        )
    connection.execute(old.insert().values(values))
    action = connection.execute(
        select(JournalAction.proposal_hash).where(JournalAction.id == ACTION)
    ).scalar_one()
    connection.execute(
        text("""INSERT INTO company_effect_intents
      (company_id,action_id,task_id,trace_id,run_id,proposal_hash,intent_fence,attempt_kind,
       state,created_at,receipt_json,verification_json)
      VALUES (:company,:action,:task,:trace,:run,:hash,1,'tool_attempts','intent',now(),NULL,NULL)
      """),
        {
            "company": COMPANY,
            "action": ACTION,
            "task": TASK,
            "trace": TRACE,
            "run": RUN,
            "hash": action,
        },
    )


async def test_live_old_lease_refuses_upgrade_then_expired_lease_retains_attempts_and_cost() -> (
    None
):
    if not settings.company_test_database_url:
        pytest.skip("explicit private populated-migration database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_lease_migration"
    engine = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(setup_old)
        factory = async_sessionmaker(app, expire_on_commit=False)
        journal, _ = await prepare(factory)
        action = await pending(journal)
        await journal.authorize_registered(
            scope(), action.action_id, NOW, SOURCES, identity=identity()
        )
        async with engine.begin() as connection:
            await connection.run_sync(seed_old_lease)
        with pytest.raises(DBAPIError, match="Drain live"):
            async with engine.begin() as connection:
                await connection.run_sync(lambda c: command.upgrade(profile_config(c), "head"))
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE company_execution_work SET lease_until = now()-interval '1 minute'")
            )
            await connection.run_sync(lambda c: command.upgrade(profile_config(c), "head"))
            row = (
                (await connection.execute(text("SELECT * FROM company_execution_work")))
                .mappings()
                .one()
            )
            assert row["state"] == "outcome_unknown" and row["fence"] == 2
            assert row["worker_id"] is None and row["lease_principal_id"] is None
            assert row["tool_attempts_used"] == 1 and row["segment_number"] == 1
            assert (
                await connection.scalar(text("SELECT state FROM company_effect_intents"))
                == "outcome_unknown"
            )
            hold = (await connection.execute(select(CostHold))).mappings().one()
            assert hold["state"] == "unknown" and hold["amount_usd"] > 0
            assert hold["actual_usd"] is None
            assert await connection.scalar(select(WorkBudget.held_usd)) == hold["amount_usd"]
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: command.downgrade(profile_config(c), "base"))
            await connection.execute(text("DROP TABLE IF EXISTS company_alembic_version"))
        await engine.dispose()
