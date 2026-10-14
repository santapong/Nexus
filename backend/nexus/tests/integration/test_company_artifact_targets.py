"""Actual owner-controlled output readership is separate from native action authority."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_access import identity, scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, migrate, prepare


@pytest.fixture
async def artifact_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_artifacts"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        factory = async_sessionmaker(app, expire_on_commit=False)
        await prepare(factory)
        yield factory
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def test_owner_provisions_exact_readers_and_replay_never_reactivates(
    artifact_factory: async_sessionmaker[AsyncSession],
) -> None:
    target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    store = ArtifactTargetStore(artifact_factory)
    first = await store.provision(scope(OWNER), identity(OWNER), target, readers=(OWNER, ACTOR))
    assert first.kind == "artifact" and first.acl_generation == 1
    await ResourceAccessStore(artifact_factory).change(
        scope(OWNER),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=target,
            principal_id=ACTOR,
            active=False,
            expected_generation=1,
        ),
    )
    replay = await store.provision(scope(OWNER), identity(OWNER), target, readers=(ACTOR, OWNER))
    assert replay.acl_generation == 2
    async with artifact_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        grant = await session.get(BrainResourceAccess, (COMPANY, target.resource_id, ACTOR))
        assert grant is not None and not grant.active
    with pytest.raises(ValueError):
        await store.provision(scope(OWNER), identity(OWNER), target, readers=(OWNER,))


@pytest.mark.parametrize("case", ["member", "principal", "foreign", "reader"])
async def test_source_read_or_supplied_identity_cannot_provision_artifact_authority(
    artifact_factory: async_sessionmaker[AsyncSession], case: str
) -> None:
    target = ResourceRef(company_id=uuid4() if case == "foreign" else COMPANY, resource_id=uuid4())
    actor = ACTOR if case == "member" else OWNER
    signed = identity(ACTOR) if case == "principal" else identity(actor)
    with pytest.raises(ValueError):
        await ArtifactTargetStore(artifact_factory).provision(
            scope(actor),
            signed,
            target,
            readers=(OWNER, uuid4()) if case == "reader" else (OWNER, ACTOR),
        )
    async with artifact_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(BrainResource, (COMPANY, target.resource_id)) is None
