"""Owner ACL changes fail closed and preserve compare-and-swap retry behavior.

The session is simulated; transactional locking and database constraints need integration tests.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore, _change_locked
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainAccessEvent, BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.directory_models import DirectoryMembership

COMPANY = UUID(int=1)
RESOURCE = UUID(int=2)
PRINCIPAL = UUID(int=3)
NOW = datetime(2026, 10, 29, tzinfo=UTC)


def scope() -> BrainReadScope:
    return BrainReadScope(
        company_id=COMPANY,
        workspace_id=UUID(int=4),
        principal_id=UUID(int=5),
        operation_id=UUID(int=6),
        trace_id=UUID(int=7),
    )


def change(
    *, active: bool = True, expected: int = 3, expires_at: datetime | None = None
) -> ResourceAccessChange:
    return ResourceAccessChange(
        company_id=COMPANY,
        resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
        principal_id=PRINCIPAL,
        active=active,
        expected_generation=expected,
        expires_at=expires_at,
    )


def resource(*, active: bool = True) -> BrainResource:
    return BrainResource(
        company_id=COMPANY,
        resource_id=RESOURCE,
        kind="source",
        active=active,
        acl_generation=3,
        created_at=NOW,
        updated_at=NOW,
    )


def member(*, active: bool = True, principal_active: bool = True) -> DirectoryMembership:
    return DirectoryMembership(
        company_id=COMPANY,
        principal_id=PRINCIPAL,
        role="member",
        membership_active=active,
        principal_active=principal_active,
    )


def grant(*, active: bool, generation: int = 2) -> BrainResourceAccess:
    return BrainResourceAccess(
        company_id=COMPANY,
        resource_id=RESOURCE,
        principal_id=PRINCIPAL,
        active=active,
        generation=generation,
        expires_at=None,
    )


def session_with(
    source: BrainResource | None,
    membership: DirectoryMembership | None,
    existing: BrainResourceAccess | None,
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = source
    session.get.side_effect = [membership, existing]
    return session


async def test_foreign_company_command_is_denied_before_opening_transaction() -> None:
    factory = MagicMock(spec=async_sessionmaker)
    foreign_company = UUID(int=99)
    command = change().model_copy(
        update={
            "company_id": foreign_company,
            "resource": ResourceRef(company_id=foreign_company, resource_id=RESOURCE),
        }
    )
    store = ResourceAccessStore(cast(async_sessionmaker[AsyncSession], factory))
    with pytest.raises(BrainDeniedError):
        await store.change(scope(), cast(VerifiedIdentity, object()), command)
    factory.assert_not_called()


@pytest.mark.parametrize(
    ("source", "membership", "expiry"),
    [
        (None, member(), None),
        (resource(), None, None),
        (resource(active=False), member(), None),
        (resource(), member(active=False), None),
        (resource(), member(principal_active=False), None),
        (resource(), member(), NOW),
        (resource(), member(), NOW - timedelta(microseconds=1)),
    ],
)
async def test_grant_rejects_unavailable_resource_member_or_expiry(
    source: BrainResource | None, membership: DirectoryMembership | None, expiry: datetime | None
) -> None:
    session = session_with(source, membership, None)
    with pytest.raises(BrainDeniedError):
        await _change_locked(cast(AsyncSession, session), scope(), change(expires_at=expiry), NOW)
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_conflicting_generation_cannot_modify_an_existing_grant() -> None:
    source, existing = resource(), grant(active=False)
    session = session_with(source, member(), existing)
    with pytest.raises(BrainConflictError):
        await _change_locked(cast(AsyncSession, session), scope(), change(expected=2), NOW)
    assert source.acl_generation == 3
    assert existing.active is False and existing.generation == 2
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_exact_retry_returns_current_snapshot_even_if_generation_is_stale() -> None:
    source, existing = resource(), grant(active=True)
    session = session_with(source, member(), existing)
    result = await _change_locked(cast(AsyncSession, session), scope(), change(expected=1), NOW)
    assert (result.active, result.generation, result.resource_generation) == (True, 2, 3)
    assert result.principal_id == PRINCIPAL and result.resource.resource_id == RESOURCE
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_new_grant_increments_generation_and_emits_owner_event() -> None:
    source = resource()
    session = session_with(source, member(), None)
    expires = NOW + timedelta(seconds=1)
    with patch("nexus.company.brain.access.append_event", new_callable=AsyncMock) as emit:
        result = await _change_locked(
            cast(AsyncSession, session), scope(), change(expires_at=expires), NOW
        )
    assert (result.active, result.generation, result.resource_generation) == (True, 4, 4)
    assert result.expires_at == expires and source.updated_at == NOW
    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 2
    assert isinstance(added[0], BrainResourceAccess)
    assert isinstance(added[1], BrainAccessEvent)
    assert (added[1].company_id, added[1].principal_id, added[1].generation) == (
        COMPANY,
        PRINCIPAL,
        4,
    )
    assert added[1].owner_id == scope().principal_id
    assert added[1].operation_id == scope().operation_id
    assert added[1].trace_id == scope().trace_id
    assert session.flush.await_count == 1
    emit.assert_awaited_once()
    assert emit.await_args is not None
    assert emit.await_args.kwargs["kind"] == "acl_changed"
    assert emit.await_args.kwargs["resource_id"] == RESOURCE
    assert emit.await_args.kwargs["resource_generation"] == 4


async def test_revocation_remains_possible_for_inactive_resource_and_member() -> None:
    source = resource(active=False)
    existing = grant(active=True)
    session = session_with(source, member(active=False, principal_active=False), existing)
    with patch("nexus.company.brain.access.append_event", new_callable=AsyncMock):
        result = await _change_locked(
            cast(AsyncSession, session), scope(), change(active=False), NOW
        )
    assert (result.active, result.generation, result.resource_generation) == (False, 4, 4)
    assert existing.active is False and existing.generation == 4
    assert len(session.add.call_args_list) == 1
    assert isinstance(session.add.call_args_list[0].args[0], BrainAccessEvent)
