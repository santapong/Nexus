"""Exclusive normal-profile view database and native public owner-plan fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.base import SourceTime
from nexus.company.management.commitment_store import CommitmentStore
from nexus.company.management.goals import DueIntent
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import plan_reference
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import configured_plan, registered_freshness


@dataclass(frozen=True)
class ViewsDatabase:
    app: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]


@pytest.fixture
async def views_database() -> AsyncIterator[ViewsDatabase]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_views"
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
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


async def configured_views(
    database: ViewsDatabase,
    root: Path,
) -> tuple[
    ManagementOwnerViews, CommitmentStore, ManagementPlanStore, PlanPayload, CommitmentDefinition
]:
    store, payload = await configured_plan(database.app, root)
    proposed = await store.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    views = ManagementOwnerViews(
        database.app,
        OwnerViewSources(
            BoundedArtifactReader(
                database.app, ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
            ),
            registered_freshness(database.app),
        ),
    )
    definition = CommitmentDefinition(
        company_id=payload.company_id,
        commitment_id=uuid4(),
        goal=payload.goal,
        plan=plan_reference(proposed),
        responsible_id=payload.children[0].binding.actor_id,
        deliverable="Owner declared internal report",
        due=DueIntent(
            source_time=SourceTime(precision="unknown", value=None, basis="No deadline supplied")
        ),
        work=tuple(child.binding for child in payload.children),
    )
    return views, CommitmentStore(database.app), store, payload, definition
