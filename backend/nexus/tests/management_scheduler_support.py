"""Exclusive scheduler database and public native plan/action setup; no live models."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dbos import DBOS
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.company.management.scheduling_contracts import (
    DueWake,
    ScanRequest,
    SchedulerPolicy,
    WorkflowRegistration,
)
from nexus.company.management.scheduling_store import ManagementScheduler
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import (
    VERIFIER,
    authorized_action,
    configured_plan,
    registered_freshness,
)

WORKFLOW = "internal.report"
VERSION = "v1"
QUEUE = "management.internal"
APPLICATION = "nexus-management-offline"


@dataclass(frozen=True)
class SchedulerDatabase:
    app: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]


@pytest.fixture
async def scheduler_database() -> AsyncIterator[SchedulerDatabase]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_scheduler"
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    await asyncio.to_thread(
        DBOS.migrate,
        url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        application_role="nexus_company_app",
    )
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield SchedulerDatabase(
            async_sessionmaker(app, expire_on_commit=False),
            async_sessionmaker(admin, expire_on_commit=False),
        )
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
                await connection.execute(text("DROP SCHEMA dbos CASCADE"))
        await admin.dispose()


class FixtureIdentities:
    """Only three predetermined verified fixture identities; nothing comes from scan content."""

    def __init__(self) -> None:
        self.identities = tuple(identity(principal) for principal in (OWNER, ACTOR, VERIFIER))

    def actor(self, binding: RunBinding) -> VerifiedIdentity:
        selected = next(
            (
                value
                for value in self.identities
                if (value.principal_id, value.workspace_id)
                == (binding.actor_id, binding.workspace_id)
            ),
            None,
        )
        if selected is None:
            raise ValueError("Fixture actor has no configured authenticated identity")
        return selected


class FixtureResources:
    """These actual exact fixture actions have no external resource preconditions."""

    async def current(
        self,
        session: AsyncSession,
        binding: RunBinding,
        proposal: ActionProposal,
        signed: VerifiedIdentity,
    ) -> tuple[ResourceRevision, ...]:
        assert not proposal.preconditions and signed.principal_id == binding.actor_id
        return ()


async def setup_scheduler(
    database: SchedulerDatabase, path: Path, *, max_tasks: int = 100, tool_attempts: int = 1
) -> tuple[ManagementScheduler, PlanPayload]:
    store, payload = await configured_plan(database.app, path)
    payload = PlanPayload.model_validate_json(
        payload.model_copy(
            update={
                "children": tuple(
                    child.model_copy(
                        update={
                            "quota": child.quota.model_copy(update={"tool_attempts": tool_attempts})
                        }
                    )
                    for child in payload.children
                )
            }
        ).model_dump_json()
    )
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
    services = SchedulerServices(
        policy=SchedulerPolicy(
            recipe_version="management.scheduler.offline.v1",
            max_tasks=max_tasks,
            workflows=(
                WorkflowRegistration(
                    workflow_name=WORKFLOW,
                    workflow_version=VERSION,
                    queue_name=QUEUE,
                    application_name=APPLICATION,
                ),
            ),
        ),
        catalog=store.catalog,
        artifacts=BoundedArtifactReader(
            database.app, ProtectedBlobStore(path, storage_symbol="fixture.blobs.v1")
        ),
        freshness=registered_freshness(database.app),
        identities=FixtureIdentities(),
        resources=FixtureResources(),
    )
    return ManagementScheduler(database.app, services), payload


async def due_request(database: SchedulerDatabase, **fields: object) -> ScanRequest:
    async with database.app() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    request = ScanRequest(
        company_id=COMPANY,
        wake=DueWake(bucket=now.astimezone(UTC).replace(second=0, microsecond=0)),
    )
    return ScanRequest.model_validate_json(request.model_copy(update=fields).model_dump_json())


__all__ = ["authorized_action", "control", "identity"]
