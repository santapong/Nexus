"""Actual normal015 schema qualification only; placeholder event rows are not native wakes."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, func, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.native_event_capability import native_event_capability
from nexus.company.brain.native_event_schema import NATIVE_EVENT_FIELDS
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, migrate
from nexus.tests.native_profile_support import ProfileScenario, configured_profile


@pytest.fixture
async def native_schema_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_schema"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            await connection.execute(
                text("GRANT DELETE ON company_brain_events TO nexus_company_app")
            )
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def test_native_event015_physical_columns_and_profile_are_qualified(
    native_schema_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with native_schema_factory() as session, session.begin():
        assert await native_event_capability(session)
        version = await session.scalar(text("SELECT version_num FROM company_alembic_version"))
        assert version == "company_015"
        connection = await session.connection()
        columns = await connection.run_sync(
            lambda sync: inspect(sync).get_columns("company_brain_events")
        )
        assert set(NATIVE_EVENT_FIELDS) <= {row["name"] for row in columns}


@pytest.mark.parametrize(
    "failure",
    [
        "task_fk",
        "report_fk",
        "day_fk",
        "old_native",
        "decision_null",
        "digest_null",
        "cap_both",
        "native_source",
    ],
)
async def test_native_event_sql_null_kind_and_real_target_shape_rejects(
    native_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    case = await configured_profile(native_schema_factory, tmp_path)
    async with native_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        values, source = await schema_event_values(session, case)
    invalidate_schema_event(values, source, case.report_id, failure)
    with pytest.raises(DBAPIError):
        async with native_schema_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(insert(cast(Table, BrainEvent.__table__)).values(**values))


async def schema_event_values(
    session: AsyncSession, case: ProfileScenario
) -> tuple[dict[str, object], UUID | None]:
    """Only SQL shape placeholders, not caller-supplied native notification evidence."""
    prior = await session.scalar(select(BrainEvent).order_by(BrainEvent.sequence).limit(1))
    assert prior is not None
    source = await session.scalar(
        select(BrainEvent.source_revision_id)
        .where(BrainEvent.source_revision_id.is_not(None))
        .limit(1)
    )
    return {
        "company_id": COMPANY,
        "event_id": uuid4(),
        "sequence": 10000,
        "kind": "work_blocked",
        "resource_id": prior.resource_id,
        "deduplication_key": uuid4().hex,
        "operation_id": uuid4(),
        "trace_id": uuid4(),
        "task_id": case.payload.children[0].binding.task_id,
        "native_snapshot_sha256": "a" * 64,
    }, source


def invalidate_schema_event(
    values: dict[str, object], source: UUID | None, report_id: UUID, failure: str
) -> None:
    """Exercise physical NULL/FK guards without treating fixtures as operational facts."""
    if failure == "task_fk":
        values["task_id"] = uuid4()
    elif failure == "report_fk":
        values.update(
            kind="digest_due",
            task_id=None,
            report_id=uuid4(),
            due_bucket="schema",
            scheduled_for=datetime.now(UTC),
            notification_policy_sha256="b" * 64,
        )
    elif failure == "day_fk":
        values.update(kind="cap_exhausted", task_id=None, budget_day=date(2000, 1, 1))
    elif failure == "old_native":
        values["kind"] = "claims_changed"
    elif failure == "decision_null":
        values["kind"] = "decision_required"
    elif failure == "digest_null":
        values.update(kind="digest_due", task_id=None, report_id=report_id)
    elif failure == "cap_both":
        values.update(kind="cap_exhausted", budget_day=date.today())
    else:
        assert source is not None
        values["source_revision_id"] = source
