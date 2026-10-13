"""Optional Brain composition in the real company factory preserves disabled intake."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.control_store import CompanyControls
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.brain_api_support import actual_services
from nexus.tests.integration.test_company_api import KEY, headers
from nexus.tests.integration.test_company_directory import COMPANY, migrate


@pytest.fixture
async def factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    if not settings.company_test_database_url:
        pytest.skip("Explicit private company Brain composition database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_brain_app"
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    async with admin.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@pytest.mark.parametrize("mount", [False, True])
async def test_optional_brain_is_authenticated_readonly_and_preserves_company_health(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, mount: bool
) -> None:
    brain = await actual_services(factory, tmp_path, b"Registered attachment text")
    core = CompanyServices(brain.directory, CompanyJournal(factory), CompanyControls(factory))
    app = create_company_app(core, brain_services=brain if mount else None)
    base = f"/api/v2/companies/{COMPANY}/brain"
    async with AsyncTestClient(app) as client:
        health = await client.get("/health")
        assert health.status_code == 200 and health.json()["intake_enabled"] is False
        search = await client.post(
            base + "/search", headers=headers(), json={"search": {"query": "attachment"}}
        )
        assert search.status_code == (200 if mount else 404)
        if mount:
            assert len(search.json()["handles"]) == 1
            denied = await client.post(base + "/search", json={"search": {"query": "attachment"}})
            assert denied.status_code == 401
        assert (await client.post(base + "/ingest", headers=headers(), json={})).status_code == 404
        assert (await client.post("/api/v2/company/work", json={})).status_code == 404
