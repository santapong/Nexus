"""Normal011 native FK/target/immutable/RLS/install proof in the assigned private DB."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_models import WorkCancellation
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.execution.runtime_models import ExecutionWork
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_cancellation import _approved
from nexus.tests.integration.test_company_profile_migrations import verify_profile
from nexus.tests.management_cancellation_support import cancellation_factory as cancellation_factory


async def test_cancellation_rows_are_forced_scoped_immutable_and_exact_native_fk_bound(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, payload, _ = await _approved(cancellation_factory, tmp_path)
    record = await WorkCancellationStore(cancellation_factory).cancel(
        control().model_copy(update={"operation_id": uuid4()}),
        identity(OWNER),
        CancellationCommand(
            company_id=COMPANY, target=payload.children[0].binding, reason="Immutable owner intent"
        ),
    )
    async with cancellation_factory() as session, session.begin():
        assert (await session.scalars(select(WorkCancellation))).all() == []
    for statement in (
        update(WorkCancellation).values(reason="Rewritten intent"),
        delete(WorkCancellation),
    ):
        with pytest.raises(DBAPIError, match="Management history is immutable"):
            async with cancellation_factory() as session, session.begin():
                await session.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                await session.execute(
                    statement.where(WorkCancellation.cancellation_id == record.cancellation_id)
                )


@pytest.mark.parametrize(
    "failure",
    [
        "trace",
        "run",
        "hash",
        "owner",
        "binding",
        "workspace_id",
        "actor_id",
        "workflow_name",
        "workflow_version",
        "model_profile",
        "model_registry_version",
    ],
)
async def test_actual_restricted_insert_cannot_forge_cancellation_native_binding(
    cancellation_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    _, payload, _ = await _approved(cancellation_factory, tmp_path)
    bound = payload.children[0].binding
    forged = (
        bound.model_copy(update={"task_id": uuid4()})
        if failure == "binding"
        else bound.model_copy(update={failure: uuid4() if failure.endswith("_id") else "forged"})
        if failure
        in {
            "workspace_id",
            "actor_id",
            "workflow_name",
            "workflow_version",
            "model_profile",
            "model_registry_version",
        }
        else bound
    )
    async with cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        actual = await session.get(ExecutionWork, (COMPANY, bound.task_id))
        assert actual is not None
        digest = actual.registration_hash
    with pytest.raises(DBAPIError):
        async with cancellation_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            session.add(
                WorkCancellation(
                    company_id=COMPANY,
                    cancellation_id=uuid4(),
                    operation_id=uuid4(),
                    task_id=bound.task_id,
                    trace_id=uuid4() if failure == "trace" else bound.trace_id,
                    run_id=uuid4() if failure == "run" else bound.run_id,
                    binding_json=forged.model_dump_json(),
                    registration_sha256="f" * 64 if failure == "hash" else digest,
                    reason="Cannot forge native intent",
                    owner_id=ACTOR if failure == "owner" else OWNER,
                    audit_trace_id=uuid4(),
                )
            )
            await session.flush()


async def test_normal011_profile_repeat_metadata_downgrade_preserves_legacy_history() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_cancellation"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            # All earlier assigned fixtures normally downgraded; remove only their empty marker.
            if (
                await connection.scalar(
                    text("SELECT to_regclass('public.company_alembic_version')")
                )
                is not None
            ):
                assert (
                    await connection.scalar(text("SELECT count(*) FROM company_alembic_version"))
                    == 0
                )
                await connection.execute(text("DROP TABLE company_alembic_version"))
            await connection.run_sync(verify_profile)
    finally:
        await engine.dispose()
