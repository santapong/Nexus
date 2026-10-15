"""Same-session full-plan metadata snapshots; no body read or native registration authority."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainSource, BrainSourceHead
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.governance import CharterRevision
from nexus.company.management.plan_admission_window import (
    PlanGrantWindow,
    PlanSourceWindow,
    require_window,
)
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload


def required_grant_pairs(
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    charters: dict[UUID, CharterRevision],
) -> tuple[tuple[UUID, UUID], ...]:
    resources = {row.symbol: row.resource.resource_id for row in catalog.resources}
    pairs = {
        (resources[name], principal)
        for child in payload.children
        for name in charters[child.charter.revision_id].charter.resource_scopes
        for principal in (
            child.binding.actor_id,
            charters[child.charter.revision_id].charter.verifier_id,
        )
    }
    require_window(len(resources) <= 32 and 1 <= len(payload.children) <= 11 and len(pairs) <= 704)
    return tuple(sorted(pairs))


async def capture_grants(
    session: AsyncSession,
    scope: BrainReadScope,
    pairs: tuple[tuple[UUID, UUID], ...],
    now: datetime,
) -> tuple[PlanGrantWindow, ...]:
    values = []
    for resource_id, principal in pairs:
        resource = await session.get(BrainResource, (scope.company_id, resource_id))
        grant = await session.get(BrainResourceAccess, (scope.company_id, resource_id, principal))
        require_window(resource is not None and resource.active and grant is not None)
        assert resource is not None and grant is not None
        require_window(grant.active and (grant.expires_at is None or now < grant.expires_at))
        values.append(
            PlanGrantWindow(
                resource_id, principal, resource.acl_generation, grant.generation, grant.expires_at
            )
        )
    return tuple(values)


async def capture_sources(
    session: AsyncSession,
    scope: BrainReadScope,
    resources: tuple[UUID, ...],
    freshness: RegisteredSourceFreshness,
    now: datetime,
) -> tuple[PlanSourceWindow, ...]:
    """Project only source/head metadata; no artifact ORM/raw_text/blob lookup occurs."""
    heads = {}
    for key in resources:
        resource = await session.get(BrainResource, (scope.company_id, key))
        require_window(resource is not None and resource.active)
        assert resource is not None
        if resource.kind != "source":
            continue
        source = await session.scalar(
            select(BrainSource).where(
                BrainSource.company_id == scope.company_id, BrainSource.resource_id == key
            )
        )
        require_window(source is not None)
        assert source is not None
        head = await session.get(BrainSourceHead, (scope.company_id, source.source_id))
        require_window(head is not None and head.availability == "available")
        assert head is not None
        heads[source.source_id] = head
    qualified = await freshness.capture_plan_heads_locked(session, scope, tuple(sorted(heads)), now)
    result = []
    for value in qualified:
        head = heads[value.source_id]
        deadline = (
            head.observed_at + timedelta(seconds=value.policy.freshness_seconds)
            if value.policy.freshness_seconds is not None
            else None
        )
        require_window(head.fresh_until == value.fresh_until == deadline)
        result.append(
            PlanSourceWindow(
                head.source_id, head.current_revision_id, head.generation, head.observed_at, value
            )
        )
    return tuple(result)


async def capture_aggregate_minima(
    session: AsyncSession,
    scope: BrainReadScope,
    catalog: PlanAdmissionCatalog,
    payload: PlanPayload,
    charters: dict[UUID, CharterRevision],
) -> tuple[datetime | None, datetime | None]:
    """Preserve the existing final check's cross-product minima without silently narrowing it."""
    resources = {
        row.resource.resource_id
        for row in catalog.resources
        if any(row.symbol in charter.charter.resource_scopes for charter in charters.values())
    }
    actors = {row.binding.actor_id for row in payload.children} | {
        row.charter.verifier_id for row in charters.values()
    }
    grants = await session.scalar(
        select(func.min(BrainResourceAccess.expires_at)).where(
            BrainResourceAccess.company_id == scope.company_id,
            BrainResourceAccess.resource_id.in_(resources),
            BrainResourceAccess.principal_id.in_(actors),
        )
    )
    sources = await session.scalar(
        select(func.min(BrainSourceHead.fresh_until))
        .join(
            BrainSource,
            (BrainSource.company_id == BrainSourceHead.company_id)
            & (BrainSource.source_id == BrainSourceHead.source_id),
        )
        .where(BrainSource.company_id == scope.company_id, BrainSource.resource_id.in_(resources))
    )
    return grants, sources
