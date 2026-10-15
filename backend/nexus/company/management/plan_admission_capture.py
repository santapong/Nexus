"""Future owner/full-plan capture; current full mixed admission remains fail-closed."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.cycle_admission import validate_stockflow_cycle
from nexus.company.management.governance import CharterRevision
from nexus.company.management.plan_admission_candidates import capture_child_window
from nexus.company.management.plan_admission_metadata import (
    capture_aggregate_minima,
    capture_grants,
    capture_sources,
    required_grant_pairs,
)
from nexus.company.management.plan_admission_window import PlanAdmissionWindow, require_window
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_support import validate_plan
from nexus.company.management.plans import PlanPayload
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class CapturedPlanAdmission:
    """Actual validated charter descriptions and temporal observations, never approval."""

    charters: dict[UUID, CharterRevision]
    window: PlanAdmissionWindow


async def _capture_plan_metadata_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    charters: dict[UUID, CharterRevision],
    freshness: RegisteredSourceFreshness,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> PlanAdmissionWindow:
    """Internal observations only; public entry must first perform actual validate_plan."""
    # This >50-line bounded read retains every first/current clock observation in one session.
    require_window(session.in_transaction() and isinstance(freshness, RegisteredSourceFreshness))
    require_window(
        (control.company_id, control.owner_id) == (scope.company_id, scope.principal_id)
        and identity.principal_id == control.owner_id
        and not control.paused
    )
    require_window(
        await session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
        is False
    )
    actual = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == scope.company_id)
        .with_for_update()
    )
    require_window(actual is control)
    read = BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=identity.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    await require_brain_scope(session, control, read, identity, owner=True)
    now = await db_clock(session)
    require_window(
        isinstance(credential, AuthenticatedWorkerIdentity) and credential.identity == identity
    )
    credential.require_time(now)
    require_window(
        payload.company_id == catalog.company_id == scope.company_id
        and catalog.models.pricebook_version == control.price_version
    )
    # Keep only alternatives qualified before later metadata awaits; future evidence cannot rescue.
    children = tuple(capture_child_window(catalog, child, now) for child in payload.children)
    pairs = required_grant_pairs(payload, catalog, charters)
    grants = await capture_grants(session, read, pairs, now)
    resources = tuple(sorted({key for key, _ in pairs}))
    sources = await capture_sources(session, read, resources, freshness, now)
    aggregate_grant, aggregate_source = await capture_aggregate_minima(
        session, read, catalog, payload, charters
    )
    final = await db_clock(session)
    window = PlanAdmissionWindow(
        control.company_id,
        control.owner_id,
        identity.workspace_id,
        canonical_sha256(payload),
        canonical_sha256(catalog),
        control.policy_version,
        control.price_version,
        now,
        children,
        grants,
        sources,
        aggregate_grant,
        aggregate_source,
        credential,
    )
    window.require_time(final)
    return window


async def capture_plan_admission_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    catalog: PlanAdmissionCatalog,
    freshness: RegisteredSourceFreshness,
    *,
    credential: AuthenticatedWorkerIdentity,
) -> CapturedPlanAdmission:
    """Always run real validation; this wrapper cannot make today's mixed plan admissible."""
    require_window(session.in_transaction() and isinstance(credential, AuthenticatedWorkerIdentity))
    require_window(credential.identity == identity and identity.principal_id == control.owner_id)
    credential.require_time(await db_clock(session))
    for quota in (payload.procedure.quota, *(child.quota for child in payload.children)):
        AttemptQuota.model_validate(
            {name: getattr(quota, name) for name in AttemptQuota.model_fields}
        )
    payload = PlanPayload.model_validate(payload.model_dump(warnings=False))
    catalog = PlanAdmissionCatalog.model_validate(catalog.model_dump(warnings=False))
    charters = await validate_plan(session, control, scope, identity, payload, catalog, freshness)
    selected = validate_stockflow_cycle(catalog.cycle_admission, catalog.models, payload)
    require_window(selected is not None and selected.stage == "full")
    window = await _capture_plan_metadata_locked(
        session,
        control,
        scope,
        identity,
        payload,
        catalog,
        charters,
        freshness,
        credential=credential,
    )
    return CapturedPlanAdmission(charters, window)
