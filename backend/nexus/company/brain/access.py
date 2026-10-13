"""Current owner-managed source ACL changes; only read access is represented here."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceAccessSnapshot
from nexus.company.brain.access_models import BrainAccessEvent, BrainResource, BrainResourceAccess
from nexus.company.brain.access_support import access_snapshot
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)
from nexus.company.directory_models import DirectoryMembership


class ResourceAccessStore:
    """Changing read ACL cannot allocate budget, grant actions or publish completed work."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def change(
        self, scope: BrainReadScope, identity: VerifiedIdentity, change: ResourceAccessChange
    ) -> ResourceAccessSnapshot:
        """Current actual owner performs compare-and-swap in the same locked transaction."""
        if change.resource.company_id != scope.company_id:
            raise BrainDeniedError("Brain resource access is unavailable")
        async with brain_transaction(self._factory, scope, identity, owner=True) as (
            session,
            _,
            now,
        ):
            return await _change_locked(session, scope, change, now)


async def _change_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    change: ResourceAccessChange,
    now: datetime,
) -> ResourceAccessSnapshot:
    resource = await session.scalar(
        select(BrainResource)
        .where(
            BrainResource.company_id == scope.company_id,
            BrainResource.resource_id == change.resource.resource_id,
        )
        .with_for_update()
    )
    member = await session.get(DirectoryMembership, (scope.company_id, change.principal_id))
    if (
        resource is None
        or member is None
        or (
            change.active
            and (
                not resource.active
                or not member.membership_active
                or not member.principal_active
                or (change.expires_at is not None and change.expires_at <= now)
            )
        )
    ):
        raise BrainDeniedError("Brain resource access is unavailable")
    grant = await session.get(
        BrainResourceAccess, (scope.company_id, resource.resource_id, change.principal_id)
    )
    if grant is not None and (grant.active, grant.expires_at) == (change.active, change.expires_at):
        return access_snapshot(resource, grant)
    if resource.acl_generation != change.expected_generation:
        raise BrainConflictError("Brain resource access changed; reload before deciding")
    return await _persist_change(session, scope, resource, grant, change, now)


async def _persist_change(
    session: AsyncSession,
    scope: BrainReadScope,
    resource: BrainResource,
    grant: BrainResourceAccess | None,
    change: ResourceAccessChange,
    now: datetime,
) -> ResourceAccessSnapshot:
    resource.acl_generation += 1
    resource.updated_at = now
    if grant is None:
        grant = BrainResourceAccess(
            company_id=scope.company_id,
            resource_id=resource.resource_id,
            principal_id=change.principal_id,
        )
        session.add(grant)
    grant.active, grant.expires_at, grant.generation = (
        change.active,
        change.expires_at,
        resource.acl_generation,
    )
    await _append_change_events(session, scope, resource, grant, change, now)
    return access_snapshot(resource, grant)


async def _append_change_events(
    session: AsyncSession,
    scope: BrainReadScope,
    resource: BrainResource,
    grant: BrainResourceAccess,
    change: ResourceAccessChange,
    now: datetime,
) -> None:
    """Grant history and ID-only invalidation become visible in the same owner transaction."""
    session.add(
        BrainAccessEvent(
            company_id=scope.company_id,
            event_id=uuid4(),
            resource_id=resource.resource_id,
            principal_id=change.principal_id,
            generation=resource.acl_generation,
            active=change.active,
            expires_at=change.expires_at,
            owner_id=scope.principal_id,
            operation_id=scope.operation_id,
            trace_id=scope.trace_id,
            recorded_at=now,
        )
    )
    await session.flush()
    key = hashlib.sha256(
        json.dumps(
            (
                str(scope.operation_id),
                str(resource.resource_id),
                str(grant.principal_id),
                grant.generation,
            ),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    await append_event(
        session,
        scope,
        kind="acl_changed",
        resource_id=resource.resource_id,
        resource_generation=resource.acl_generation,
        deduplication_key=key,
        now=now,
    )
