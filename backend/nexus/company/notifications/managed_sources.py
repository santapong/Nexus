"""Bounded same-session managed qualification deadlines; no bytes, owner impersonation or permit."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_models import BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import current_charter
from nexus.company.management.model_observations import effective_model_registration
from nexus.company.management.native_profile_admission import control_scope
from nexus.company.management.operating_report_resources import report_resources
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_profile
from nexus.company.management.plans import PlanPayload
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.native_profile_checks import native_notification_profile
from nexus.execution.runtime_support import db_now


async def plan_resources(
    session: AsyncSession,
    scope: BrainReadScope,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    resources = {row.symbol: row.resource.resource_id for row in catalog.resources}
    required: set[UUID] = set()
    actors = {row.binding.actor_id for row in payload.children}
    for reference in payload.charters:
        current = await current_charter(session, control_scope(scope), reference)
        if not set(current.charter.resource_scopes) <= resources.keys():
            raise NotificationUnavailableError("Managed notification plan resources are unknown")
        required.update(resources[name] for name in current.charter.resource_scopes)
        actors.add(current.charter.verifier_id)
    if not required or len(required) > 32:
        raise NotificationUnavailableError("Managed notification source scope exceeds its bound")
    return tuple(sorted(required)), tuple(sorted(actors))


async def protection_deadlines(
    session: AsyncSession,
    scope: BrainReadScope,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    freshness: RegisteredSourceFreshness,
    draft: NotificationDraft,
) -> tuple[datetime, ...]:
    resources, actors = await plan_resources(session, scope, payload, catalog)
    required, _, heads = await report_resources(
        session, scope, resources, draft.provenance.artifacts
    )
    await freshness.revalidate_references(
        session, scope, draft.provenance.artifacts, await db_now(session)
    )
    grants = await require_resources(session, scope, required, await db_now(session))
    expiry = await session.scalar(
        select(func.min(BrainResourceAccess.expires_at)).where(
            BrainResourceAccess.company_id == scope.company_id,
            BrainResourceAccess.resource_id.in_(resources),
            BrainResourceAccess.principal_id.in_(actors),
        )
    )
    values = tuple(row.expires_at for row in grants if row.expires_at is not None)
    values += tuple(row.fresh_until for row in heads if row.fresh_until is not None)
    values += (expiry,) if expiry is not None else ()
    return values


def profile_deadlines(
    payload: PlanPayload, catalog: PlanAdmissionCatalog, now: datetime
) -> tuple[datetime, ...]:
    """One current actual registered health/evaluation pair narrows each child's final clock."""
    deadlines = []
    for child in payload.children:
        validate_plan_profile(catalog, child, now)
        if native_notification_profile(catalog, child) is not None:
            continue
        available = [
            min(model.health.expires_at, evaluation.expires_at)
            for original in catalog.models.models
            for model in (
                effective_model_registration(catalog.models, catalog.model_observations, original),
            )
            for evaluation in model.evaluations
            if model.enabled
            and model.health.status == "healthy"
            and model.health.checked_at <= now < model.health.expires_at
            and evaluation.profile == child.binding.model_profile
            and evaluation.conformance_passed
            and evaluation.evaluated_at <= now < evaluation.expires_at
        ]
        if not available:
            raise NotificationUnavailableError("Managed notification profile is unavailable")
        deadlines.append(max(available))
    return tuple(deadlines)
