"""Assigned management controls DB normal migration fixture and actual current owner setup."""

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.company import CompanyMandate, DepartmentCharter
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, migrate

DEPARTMENT, GOAL = UUID(int=5000), UUID(int=5001)


def mandate(version: str = "v1", *, daily: str = "5", work: str = "1") -> CompanyMandate:
    return CompanyMandate(
        company_id=COMPANY,
        owner_id=OWNER,
        version=version,
        purpose="Bounded internal company report",
        goals=(GOAL,),
        daily_cap_usd=Decimal(daily),
        work_cap_usd=Decimal(work),
    )


def charter(version: str = "v1", *, verifier: UUID = ACTOR) -> DepartmentCharter:
    return DepartmentCharter(
        company_id=COMPANY,
        department_id=DEPARTMENT,
        name="research",
        version=version,
        responsibilities=("Prepare an evidence-linked internal report",),
        allowed_tools=("internal.report",),
        resource_scopes=("company.report",),
        deliverables=("Cited report",),
        verifier_id=verifier,
    )


@pytest.fixture
async def management_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_controls"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()
