"""Dedicated real HTTP profile; signed synthetic test identities do not grant production access."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from litestar import Litestar
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.action_review_store import OwnerActionReviewStore
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.plans import PlanPayload
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.management_views_support import ViewsDatabase, configured_views


@pytest.fixture
async def views_api_database(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ViewsDatabase]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_views_api"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield ViewsDatabase(
            async_sessionmaker(app, expire_on_commit=False),
            async_sessionmaker(admin, expire_on_commit=False),
        )
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def configured_api(
    database: ViewsDatabase,
    root: Path,
    *,
    read_enabled: bool = True,
) -> tuple[Litestar, PlanPayload, CommitmentDefinition]:
    views, commitments, plans, payload, definition = await configured_views(database, root)
    directory = PersistentCompanyDirectory(database.app)
    reader = PersistentBrainRetriever(
        database.app,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    management = ManagementApiServices(
        directory,
        ManagementControlStore(database.app),
        GoalStore(database.app, reader),
        plans,
        views if read_enabled else None,
        commitments if read_enabled else None,
        OwnerActionReviewStore(database.app, plans.catalog, views.sources)
        if read_enabled and views.sources is not None
        else None,
    )
    app = create_company_app(
        CompanyServices(directory, CompanyJournal(database.app), CompanyControls(database.app)),
        management_services=management,
    )
    return app, payload, definition
