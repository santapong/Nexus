"""Real current ACL, owner, scope and immutable history checks in one private database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainAccessEvent, BrainResource, BrainResourceAccess
from nexus.company.brain.access_support import readable_resource_ids, require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.scope_support import BrainConflictError, brain_transaction
from nexus.company.directory_models import DirectoryMembership
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    WORKSPACE,
    migrate,
    prepare,
    work,
)
from nexus.tests.integration.test_company_directory import control as directory_control

RESOURCE = UUID(int=1200)


def scope(principal: UUID = ACTOR) -> BrainReadScope:
    return BrainReadScope(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        principal_id=principal,
        operation_id=UUID(int=1201),
        trace_id=UUID(int=1202),
    )


def identity(principal: UUID = ACTOR) -> VerifiedIdentity:
    return VerifiedIdentity(principal_id=principal, workspace_id=WORKSPACE)


def change(principal: UUID, *, active: bool = True, generation: int = 1) -> ResourceAccessChange:
    return ResourceAccessChange(
        company_id=COMPANY,
        resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
        principal_id=principal,
        active=active,
        expected_generation=generation,
    )


@dataclass(frozen=True)
class AccessDatabase:
    app: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]


@pytest.fixture
async def database() -> AsyncIterator[AccessDatabase]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_brain_access"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    async with admin.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    factory = async_sessionmaker(app, expire_on_commit=False)
    try:
        await prepare(factory)
        async with brain_transaction(factory, scope(OWNER), identity(OWNER), owner=True) as (
            session,
            _,
            now,
        ):
            session.add(
                BrainResource(
                    company_id=COMPANY,
                    resource_id=RESOURCE,
                    kind="source",
                    active=True,
                    acl_generation=1,
                    created_at=now,
                    updated_at=now,
                )
            )
        yield AccessDatabase(factory, async_sessionmaker(admin, expire_on_commit=False))
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def test_current_owner_has_no_implicit_source_read_grant(database: AccessDatabase) -> None:
    async with brain_transaction(database.app, scope(OWNER), identity(OWNER)) as (session, _, now):
        assert (await session.scalars(readable_resource_ids(scope(OWNER), now))).all() == []
        with pytest.raises(ValueError, match="unavailable"):
            await require_resources(session, scope(OWNER), (RESOURCE,), now)
    grant = await ResourceAccessStore(database.app).change(
        scope(OWNER), identity(OWNER), change(OWNER)
    )
    assert grant.resource_generation == grant.generation == 2
    async with brain_transaction(database.app, scope(OWNER), identity(OWNER)) as (session, _, now):
        allowed = await require_resources(session, scope(OWNER), (RESOURCE,), now)
        assert allowed[0].generation == 2


async def test_revoke_advances_current_acl_and_commits_id_only_event_once(
    database: AccessDatabase,
) -> None:
    store = ResourceAccessStore(database.app)
    grant = await store.change(scope(OWNER), identity(OWNER), change(ACTOR))
    assert await store.change(scope(OWNER), identity(OWNER), change(ACTOR)) == grant
    revoked = await store.change(
        scope(OWNER), identity(OWNER), change(ACTOR, active=False, generation=2)
    )
    assert revoked.generation == revoked.resource_generation == 3 and not revoked.active
    async with brain_transaction(database.app, scope(), identity()) as (session, _, now):
        with pytest.raises(ValueError, match="unavailable"):
            await require_resources(session, scope(), (RESOURCE,), now)
        assert await session.scalar(select(func.count()).select_from(BrainAccessEvent)) == 2
        events = (await session.scalars(select(BrainEvent).order_by(BrainEvent.sequence))).all()
        assert [event.resource_generation for event in events] == [2, 3]
        assert all(
            event.kind == "acl_changed" and event.source_revision_id is None for event in events
        )


async def test_stale_cas_cannot_regrant_a_revoked_resource(database: AccessDatabase) -> None:
    store = ResourceAccessStore(database.app)
    await store.change(scope(OWNER), identity(OWNER), change(ACTOR))
    await store.change(scope(OWNER), identity(OWNER), change(ACTOR, active=False, generation=2))
    with pytest.raises(BrainConflictError, match="changed"):
        await store.change(scope(OWNER), identity(OWNER), change(ACTOR))
    async with brain_transaction(database.app, scope(), identity()) as (session, _, now):
        assert (await session.scalars(readable_resource_ids(scope(), now))).all() == []


async def test_members_cannot_grant_or_impersonate_owner_scope(database: AccessDatabase) -> None:
    with pytest.raises(ValueError):
        await ResourceAccessStore(database.app).change(scope(), identity(), change(ACTOR))
    with pytest.raises(ValueError):
        await ResourceAccessStore(database.app).change(scope(OWNER), identity(), change(ACTOR))
    with pytest.raises(ValueError):
        async with brain_transaction(database.admin, scope(OWNER), identity(OWNER)):
            raise AssertionError("Elevated application connection unexpectedly admitted")


async def test_reactivated_or_cached_scope_cannot_bypass_current_membership(
    database: AccessDatabase,
) -> None:
    await ResourceAccessStore(database.app).change(scope(OWNER), identity(OWNER), change(ACTOR))
    async with brain_transaction(database.app, scope(OWNER), identity(OWNER), owner=True) as (
        session,
        _,
        _,
    ):
        member = await session.get(DirectoryMembership, (COMPANY, ACTOR))
        assert member is not None
        member.membership_active = False
    with pytest.raises(ValueError):
        async with brain_transaction(database.app, scope(), identity()):
            raise AssertionError("Inactive membership unexpectedly admitted")


async def test_expired_grant_and_spliced_work_binding_fail_current_materialization(
    database: AccessDatabase,
) -> None:
    async with brain_transaction(database.app, scope(OWNER), identity(OWNER), owner=True) as (
        session,
        _,
        now,
    ):
        session.add(
            BrainResourceAccess(
                company_id=COMPANY,
                resource_id=RESOURCE,
                principal_id=ACTOR,
                active=True,
                generation=1,
                expires_at=now - timedelta(seconds=1),
            )
        )
    async with brain_transaction(database.app, scope(), identity()) as (session, _, now):
        assert (await session.scalars(readable_resource_ids(scope(), now))).all() == []
    directory = await prepare(database.app)
    registered = work()
    await directory.register_work(registered, directory_control())
    bad = scope().model_copy(
        update={
            "task_id": registered.task_id,
            "task_trace_id": UUID(int=1299),
            "actor_id": ACTOR,
        }
    )
    with pytest.raises(ValueError):
        async with brain_transaction(database.app, bad, identity()):
            raise AssertionError("Spliced trace unexpectedly admitted")


async def test_row_security_and_history_guards_survive_direct_application_sql(
    database: AccessDatabase,
) -> None:
    await ResourceAccessStore(database.app).change(scope(OWNER), identity(OWNER), change(ACTOR))
    async with database.app() as session:
        assert (await session.scalars(select(BrainResource))).all() == []
    async with database.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(UUID(int=999)), True)))
        assert (await session.scalars(select(BrainResource))).all() == []
    with pytest.raises(DBAPIError, match="immutable"):
        async with brain_transaction(database.app, scope(OWNER), identity(OWNER), owner=True) as (
            session,
            _,
            _,
        ):
            await session.execute(update(BrainAccessEvent).values(active=False))
    with pytest.raises(DBAPIError, match="invalid"):
        async with brain_transaction(database.app, scope(OWNER), identity(OWNER), owner=True) as (
            session,
            _,
            _,
        ):
            await session.execute(update(BrainResource).values(acl_generation=0))
