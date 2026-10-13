"""ACL filtering precedes ranking; current resources are rechecked before materialization."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import (
    ResourceAccessSnapshot,
    ResourceGeneration,
    ResourceRef,
)
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import BrainDeniedError


def readable_resource_ids(scope: BrainReadScope, now: datetime) -> Select[tuple[UUID]]:
    """Use as a SQL subquery before rank, limit, snippets, counts or graph expansion."""
    return (
        select(BrainResource.resource_id)
        .join(
            BrainResourceAccess,
            (BrainResourceAccess.company_id == BrainResource.company_id)
            & (BrainResourceAccess.resource_id == BrainResource.resource_id),
        )
        .where(
            BrainResource.company_id == scope.company_id,
            BrainResource.active.is_(True),
            BrainResourceAccess.principal_id == scope.principal_id,
            BrainResourceAccess.active.is_(True),
            or_(BrainResourceAccess.expires_at.is_(None), BrainResourceAccess.expires_at > now),
        )
    )


async def require_resources(
    session: AsyncSession,
    scope: BrainReadScope,
    resource_ids: tuple[UUID, ...],
    now: datetime,
) -> tuple[ResourceGeneration, ...]:
    """Caller holds CompanyControl and current scope; owner has no implicit resource grant."""
    if len(resource_ids) > 32 or len(set(resource_ids)) != len(resource_ids):
        raise BrainDeniedError("Brain resource request exceeds its boundary")
    if not resource_ids:
        return ()
    rows = (
        await session.execute(
            select(BrainResource, BrainResourceAccess)
            .join(
                BrainResourceAccess,
                (BrainResourceAccess.company_id == BrainResource.company_id)
                & (BrainResourceAccess.resource_id == BrainResource.resource_id),
            )
            .where(
                BrainResource.company_id == scope.company_id,
                BrainResource.resource_id.in_(resource_ids),
                BrainResource.resource_id.in_(readable_resource_ids(scope, now)),
                BrainResourceAccess.principal_id == scope.principal_id,
            )
        )
    ).all()
    if len(rows) != len(resource_ids):
        raise BrainDeniedError("Brain resource access is unavailable")
    versions = {
        resource.resource_id: ResourceGeneration(
            company_id=scope.company_id,
            resource_id=resource.resource_id,
            generation=resource.acl_generation,
            expires_at=grant.expires_at,
        )
        for resource, grant in rows
    }
    return tuple(versions[key] for key in resource_ids)


def access_snapshot(resource: BrainResource, grant: BrainResourceAccess) -> ResourceAccessSnapshot:
    """Expose stored grant state and distinct current resource-wide CAS generation."""
    return ResourceAccessSnapshot(
        company_id=resource.company_id,
        resource=ResourceRef(company_id=resource.company_id, resource_id=resource.resource_id),
        principal_id=grant.principal_id,
        active=grant.active,
        generation=grant.generation,
        resource_generation=resource.acl_generation,
        expires_at=grant.expires_at,
    )
