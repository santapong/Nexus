"""Actual owner provisioned artifact readership; it confers no work, spend or write permit."""

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRecord, ResourceRef
from nexus.company.brain.access_models import BrainAccessEvent, BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)
from nexus.company.directory_models import DirectoryMembership


def resource_record(row: BrainResource) -> ResourceRecord:
    return ResourceRecord.model_validate(
        {
            "company_id": row.company_id,
            "resource_id": row.resource_id,
            "kind": row.kind,
            "active": row.active,
            "acl_generation": row.acl_generation,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


async def require_initial_readers(
    session: AsyncSession, scope: BrainReadScope, target: ResourceRef, readers: tuple[UUID, ...]
) -> None:
    original = (
        await session.scalars(
            select(BrainAccessEvent).where(
                BrainAccessEvent.company_id == scope.company_id,
                BrainAccessEvent.resource_id == target.resource_id,
                BrainAccessEvent.generation == 1,
            )
        )
    ).all()
    if {row.principal_id for row in original} != set(readers) or any(
        not row.active for row in original
    ):
        raise BrainConflictError("Artifact initial readership cannot be rebound by replay")


async def insert_artifact_target(
    session: AsyncSession,
    scope: BrainReadScope,
    target: ResourceRef,
    readers: tuple[UUID, ...],
    now: datetime,
) -> BrainResource:
    for principal in readers:
        member = await session.get(DirectoryMembership, (scope.company_id, principal))
        if member is None or not member.membership_active or not member.principal_active:
            raise BrainDeniedError("Artifact readership is unavailable")
    resource = BrainResource(
        company_id=scope.company_id,
        resource_id=target.resource_id,
        kind="artifact",
        active=True,
        acl_generation=1,
        created_at=now,
        updated_at=now,
    )
    session.add(resource)
    await session.flush()
    for principal in readers:
        session.add(
            BrainResourceAccess(
                company_id=scope.company_id,
                resource_id=target.resource_id,
                principal_id=principal,
                active=True,
                generation=1,
                expires_at=None,
            )
        )
        session.add(
            BrainAccessEvent(
                company_id=scope.company_id,
                event_id=uuid5(target.resource_id, f"artifact-initial-reader:{principal}"),
                resource_id=target.resource_id,
                principal_id=principal,
                generation=1,
                active=True,
                expires_at=None,
                owner_id=scope.principal_id,
                operation_id=scope.operation_id,
                trace_id=scope.trace_id,
                recorded_at=now,
            )
        )
    await session.flush()
    await append_event(
        session,
        scope,
        kind="acl_changed",
        resource_id=target.resource_id,
        deduplication_key=f"artifact-target:{target.resource_id}:1",
        now=now,
        resource_generation=1,
    )
    return resource


class ArtifactTargetStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def provision(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        target: ResourceRef,
        *,
        readers: tuple[UUID, ...],
    ) -> ResourceRecord:
        """Create explicit reader grants once; later replay never restores revoked access."""
        target = ResourceRef.model_validate_json(target.model_dump_json())
        if (
            target.company_id != scope.company_id
            or not 1 <= len(readers) <= 32
            or len(set(readers)) != len(readers)
        ):
            raise BrainDeniedError("Artifact target scope is unavailable")
        async with brain_transaction(self.factory, scope, identity, owner=True) as (
            session,
            _,
            now,
        ):
            existing = await session.get(BrainResource, (scope.company_id, target.resource_id))
            if existing is not None:
                if existing.kind != "artifact":
                    raise BrainConflictError("Resource identity already has another kind")
                await require_initial_readers(session, scope, target, readers)
                return resource_record(existing)
            return resource_record(
                await insert_artifact_target(session, scope, target, readers, now)
            )
