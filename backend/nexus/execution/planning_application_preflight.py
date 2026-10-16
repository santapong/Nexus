"""Read-only existing-company planning readiness before registration, leases or SDK work."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import brain_transaction, require_brain_scope
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.control_support import current_charter, current_mandate, db_clock
from nexus.company.management.goal_store import GoalStore
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.planning_application import PlanningApplication, require_planning_http_signer
from nexus.execution.planning_application_config import PlanningApplicationConfig
from nexus.execution.planning_services import current
from nexus.execution.qualification_application import preflight_qualification_database
from nexus.harness.journal_models import CompanyControl


async def _governance(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    config: PlanningApplicationConfig,
    end_us: int,
) -> None:
    admission = config.admission
    goal = await GoalStore._current(session, scope, config.goal)
    mandate = await current_mandate(session, scope, admission.mandate)
    if (
        goal.definition.owner_id != control.owner_id
        or goal.definition.mandate != admission.mandate
        or mandate.mandate.owner_id != control.owner_id
        or mandate.mandate.oversight != "supervised"
        or mandate.mandate.self_improvement_enabled is not False
        or not Decimal(0)
        < mandate.mandate.work_cap_usd
        <= mandate.mandate.daily_cap_usd
        <= Decimal(5)
        or admission.procedure.allocation_usd > mandate.mandate.work_cap_usd
        or (mandate.mandate.goals and config.goal.goal_id not in mandate.mandate.goals)
    ):
        raise ValueError("Planning current goal/mandate or supervised limits differ")
    for charter in dict.fromkeys(slot.child.charter for slot in admission.slots):
        current(end_us)
        actual = await current_charter(session, scope, charter)
        if actual.mandate != admission.mandate or actual.recorded_by != control.owner_id:
            raise ValueError("Planning configured current charter differs")


def _control(control: CompanyControl, config: PlanningApplicationConfig) -> None:
    if (
        control.paused
        or control.owner_id != config.admission.procedure.binding.actor_id
        or control.policy_version != config.policy_version
        or control.price_version != config.catalog.models.pricebook_version
        or not Decimal(0) < control.work_cap_usd <= control.daily_cap_usd <= Decimal(5)
        or config.admission.procedure.allocation_usd > control.work_cap_usd
    ):
        raise ValueError("Planning current owner/policy/prices or US5/day limits differ")


async def _native(
    services: PlanningApplication,
    witness: AuthenticatedWorkerIdentity,
    end_us: int,
) -> None:
    config, actor = services.config, services.config.admission.slots[0].child.binding
    admission = config.admission
    scope = BrainReadScope(
        company_id=admission.company_id,
        workspace_id=actor.workspace_id,
        principal_id=actor.actor_id,
        operation_id=uuid4(),
        trace_id=uuid4(),
    )
    # Taskless diagnostic READ works before owner approval registers L.
    # Fresh prepare/dispatch/effects retain their existing bound-work/lease guards.
    async with brain_transaction(services.runtime.factory, scope, witness.identity) as (
        session,
        control,
        _,
    ):
        _control(control, config)
        # Actual active owner membership is read separately from the configured L actor.
        owner_member = await session.get(DirectoryMembership, (scope.company_id, control.owner_id))
        if (
            owner_member is None
            or owner_member.role != "owner"
            or not (owner_member.principal_active and owner_member.membership_active)
        ):
            raise ValueError("Planning current owner membership is unavailable")
        owner = CompanyControlScope(
            company_id=scope.company_id,
            principal_id=control.owner_id,
            operation_id=scope.operation_id,
            trace_id=scope.trace_id,
        )
        await _governance(session, control, owner, config, end_us)
        # Final actual directory/DB clock checks retain the original witness deadline.
        await require_brain_scope(session, control, scope, witness.identity)
        witness.require_time(await db_clock(session))
        current(end_us)


async def preflight_planning_database(services: PlanningApplication, *, end_us: int) -> None:
    """Minimal boot only; issued history does not require a fresh actor, Goal or provider key."""
    current(end_us)
    services.require_composition()
    require_planning_http_signer(services)
    await preflight_qualification_database(
        services.runtime.factory, end_us=end_us, schema_versions=("company_016", "company_017")
    )
    services.require_composition()
    require_planning_http_signer(services)
    current(end_us)


async def preflight_planning_application(
    services: PlanningApplication,
    *,
    end_us: int,
    require_provider_keys: bool = False,
) -> None:
    """Explicit fresh-readiness diagnostic, never a boot prerequisite or an effect permit.

    Current metadata may age while owner controls and issued historical replay
    stay available. Fresh preparation/dispatch/pre-SDK still perform native gates.
    """
    current(end_us)
    services.require_composition()
    async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
        witness = await services.runtime.identities.current()
        actor = services.config.admission.slots[0].child.binding
        if (witness.identity.principal_id, witness.identity.workspace_id) != (
            actor.actor_id,
            actor.workspace_id,
        ):
            raise ValueError("Planning credential differs from the configured actual actor")
        await preflight_qualification_database(
            services.runtime.factory, end_us=end_us, schema_versions=("company_016", "company_017")
        )
        await _native(services, witness, end_us)
        if require_provider_keys:
            row = next(
                row
                for row in services.config.catalog.models.models
                if row.registry_id == services.config.registry_id
            )
            current(end_us)
            await services.runtime.resolver.resolve(row.endpoint_id)
        if await services.runtime.identities.current() != witness:
            raise ValueError("Planning readiness credential changed its original window")
        await _native(services, witness, end_us)
    services.require_composition()
    current(end_us)
