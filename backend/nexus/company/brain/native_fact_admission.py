"""Finite current pending-decision admission deadlines, retained across final DB awaits."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_models import BrainResourceAccess
from nexus.company.brain.native_fact_contracts import DecisionState
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.control_support import charter_record
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.revision_store import plan_record


def profile_deadline(services: NativeFactServices, profile: str, now: datetime) -> datetime:
    candidates = []
    for model in services.catalog.models.models:
        if (
            not model.enabled
            or model.health.status != "healthy"
            or not model.health.checked_at <= now < model.health.expires_at
        ):
            continue
        evaluations = [
            row.expires_at
            for row in model.evaluations
            if row.profile == profile
            and row.conformance_passed
            and row.evaluated_at <= now < row.expires_at
        ]
        if evaluations:
            candidates.append(min(model.health.expires_at, max(evaluations)))
    if not candidates:
        raise BrainDeniedError("Native decision profile evidence is unavailable")
    return max(candidates)


async def decision_deadlines(
    session: AsyncSession,
    state: DecisionState,
    services: NativeFactServices,
    now: datetime,
) -> tuple[datetime, ...]:
    row = await session.get(ManagementPlanRevision, (state.company_id, state.plan.plan_revision_id))
    if row is None:
        raise BrainDeniedError("Native decision exact plan is unavailable")
    payload = plan_record(row).payload
    principals = {child.binding.actor_id for child in payload.children}
    names: set[str] = set()
    for ref in payload.charters:
        stored = await session.get(ManagementCharterRevision, (state.company_id, ref.revision_id))
        if stored is None:
            raise BrainDeniedError("Native decision charter is unavailable")
        charter = await charter_record(session, stored)
        principals.add(charter.charter.verifier_id)
        names.update(charter.charter.resource_scopes)
    resources = {
        row.resource.resource_id for row in services.catalog.resources if row.symbol in names
    }
    expiries = tuple(
        (
            await session.scalars(
                select(BrainResourceAccess.expires_at)
                .where(
                    BrainResourceAccess.company_id == state.company_id,
                    BrainResourceAccess.resource_id.in_(resources),
                    BrainResourceAccess.principal_id.in_(principals),
                    BrainResourceAccess.active.is_(True),
                    BrainResourceAccess.expires_at.is_not(None),
                )
                .limit(3201)
            )
        ).all()
    )
    if len(expiries) > 3200:
        raise BrainDeniedError("Native decision grant scope exceeds its bound")
    deadlines = {value for value in expiries if value is not None}
    deadlines.update(
        profile_deadline(services, child.binding.model_profile, now) for child in payload.children
    )
    return tuple(sorted(deadlines))
