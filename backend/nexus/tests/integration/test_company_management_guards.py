"""Normal009 restricted-SQL proof for all management policies and history/pointer guards."""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.management.models import (
    ManagementBase,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.scheduling_models import ManagementSchedulerScan, SchedulingBase
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, migrate, prepare


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_guards"
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    async with admin.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
        await connection.execute(
            text(
                "GRANT DELETE ON company_management_mandate_heads, "
                "company_management_scheduler_scans TO nexus_company_app"
            )
        )
    try:
        source = async_sessionmaker(app, expire_on_commit=False)
        await prepare(source)
        yield source
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def seed_heads(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        now = await session.scalar(select(func.clock_timestamp()))
        assert now is not None
        for version in (1, 2):
            session.add(
                ManagementMandateRevision(
                    company_id=COMPANY,
                    revision_id=UUID(int=version + 100),
                    version=f"fixture-v{version}",
                    owner_id=OWNER,
                    recorded_by=OWNER,
                    sha256="a" * 64,
                    payload_json="{}",
                    recorded_at=now - timedelta(days=3 - version),
                )
            )
        await session.flush()
        session.add(
            ManagementMandateHead(
                company_id=COMPANY,
                current_revision_id=UUID(int=102),
                active=True,
            )
        )


async def test_all_management_tables_force_native_company_policy(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname LIKE 'company_management_%' AND relkind='r'"
                )
            )
        ).all()
        assert (
            len(rows)
            == len(ManagementBase.metadata.tables) + len(SchedulingBase.metadata.tables)
            == 23
        )
        assert all(enabled and forced for _, enabled, forced in rows)


@pytest.mark.parametrize("mutation", ["history", "rollback", "identity", "delete"])
async def test_direct_application_sql_cannot_rewrite_history_or_current_identity(
    factory: async_sessionmaker[AsyncSession], mutation: str
) -> None:
    await seed_heads(factory)
    expected = {
        "history": "history is immutable",
        "rollback": "pointer cannot roll back",
        "identity": "identity is immutable",
        "delete": "current state cannot be deleted",
    }
    with pytest.raises(DBAPIError, match=expected[mutation]):
        async with factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            statements = {
                "history": "UPDATE company_management_mandate_revisions SET payload_json='changed'",
                "rollback": (
                    "UPDATE company_management_mandate_heads SET current_revision_id=:older"
                ),
                "identity": "UPDATE company_management_mandate_heads SET company_id=:foreign",
                "delete": "DELETE FROM company_management_mandate_heads",
            }
            await session.execute(
                text(statements[mutation]),
                {
                    "older": UUID(int=101),
                    "foreign": UUID(int=999),
                },
            )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(ManagementMandateHead, COMPANY)
        assert current is not None and current.current_revision_id == UUID(int=102)
        await session.execute(select(func.set_config("nexus.company_id", str(UUID(int=999)), True)))
        assert (await session.scalars(select(ManagementMandateHead))).all() == []


@pytest.mark.parametrize("mutation", ["update", "delete"])
async def test_scheduler_receipts_cannot_be_rewritten_by_application_sql(
    factory: async_sessionmaker[AsyncSession], mutation: str
) -> None:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            ManagementSchedulerScan(
                company_id=COMPANY,
                scan_id=UUID(int=771),
                consumer="nexus.management.scan",
                recipe_version="v1",
                event_key="due:fixture",
                request_sha256="b" * 64,
                result_json="{}",
                owner_id=OWNER,
                operation_id=UUID(int=772),
                trace_id=UUID(int=773),
                start_brain_sequence=0,
                end_brain_sequence=1,
                start_control_sequence=0,
                end_control_sequence=1,
                due_bucket=None,
            )
        )
    with pytest.raises(DBAPIError, match="history is immutable"):
        async with factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(
                text(
                    "UPDATE company_management_scheduler_scans SET result_json='changed'"
                    if mutation == "update"
                    else "DELETE FROM company_management_scheduler_scans"
                )
            )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(UUID(int=999)), True)))
        assert (await session.scalars(select(ManagementSchedulerScan))).all() == []
