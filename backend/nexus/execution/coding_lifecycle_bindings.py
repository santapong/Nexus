"""Actual owner/native full-r2 reads; returned descriptors never substitute actor authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.action_review_resources import (
    action_resource_symbols,
    review_named_artifacts,
)
from nexus.company.management.action_review_store import review_disclosure
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import current_charter, current_mandate, db_clock
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.nexus_coding_catalog import select_configured_nexus_plan
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.revision_store import plan_reference
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_services import CodingServices
from nexus.execution.nexus_cycle_partition import require_nexus_owner_family_locked
from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True, slots=True)
class CodingBundle:
    plan: PlanRevision
    binding: CurrentPlanBinding
    work: ExecutionSnapshot


async def owner_locked(
    services: CodingServices,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    end_us: int,
) -> int:
    """Minimal genuine current-owner metadata READ, independent of fresh C/Goal/key state."""
    services.require_composition()
    require_time(end_us)
    admission = services.management.catalog.nexus_coding_admission
    assert admission is not None
    if (
        type(owner) is not AuthenticatedWorkerIdentity
        or not session.in_transaction()
        or (
            scope.company_id,
            scope.principal_id,
            owner.identity.principal_id,
            owner.identity.workspace_id,
        )
        != (
            admission.company_id,
            control.owner_id,
            control.owner_id,
            admission.procedure.binding.workspace_id,
        )
        or control.owner_id != admission.procedure.binding.actor_id
    ):
        raise ManagementDeniedError("Coding requires its actual current configured owner")
    before = clock_us()
    now = await db_clock(session)
    owner.require_time(now)
    end_us = min(end_us, before + (owner.expires_at - now) // timedelta(microseconds=1))
    services.require_composition()
    require_time(end_us)
    return end_us


async def approved_r2_locked(
    services: CodingServices,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    end_us: int,
) -> tuple[CodingBundle, int]:
    """Cohesion exception: actual full approved native family/Goal/owner chain stays adjacent."""
    end_us = await owner_locked(services, session, control, scope, owner, end_us)
    admission = services.management.catalog.nexus_coding_admission
    assert admission is not None
    record = await require_nexus_owner_family_locked(
        session,
        control,
        scope,
        owner.identity,
        admission=admission,
        catalog=services.management.catalog,
    )
    if (
        select_configured_nexus_plan(services.management.catalog, record.payload) != "execution"
        or record.revision != 2
    ):
        raise ManagementDeniedError("Coding requires its actual approved full r2")
    head = await session.get(ManagementPlanHead, (scope.company_id, admission.plan_id))
    decision = (
        await session.get(ManagementOwnerDecision, (scope.company_id, head.decision_id))
        if head
        else None
    )
    slot = admission.slots[1]
    bound = await ManagementPlanStore.current_binding(session, scope.company_id, slot.work.task_id)
    work = await session.get(ExecutionWork, (scope.company_id, slot.work.task_id))
    goal = await GoalStore._current(session, scope, admission.goal)
    mandate = await current_mandate(session, scope, admission.mandate)
    charter = await current_charter(session, scope, slot.child.charter)
    if (
        head is None
        or head.state != "approved"
        or head.current_revision_id != record.plan_revision_id
        or decision is None
        or decision.kind != "approve"
        or decision.owner_id != control.owner_id
        or bound is None
        or bound.plan != plan_reference(record)
        or work is None
        or bound.child != slot.child
        or bound.work != slot.work
        or goal.definition.owner_id != control.owner_id
        or goal.definition.mandate != admission.mandate
        or mandate.mandate.owner_id != control.owner_id
        or charter.mandate != admission.mandate
        or record.sha256 != canonical_sha256(record.payload)
        or record.payload.coding_admission_sha256 != canonical_sha256(admission)
    ):
        raise ManagementDeniedError("Coding actual approved r2/owner/Goal/registration differs")
    native = snapshot(work)
    if (
        native.registration.work != slot.work
        or native.registration.run_id != slot.child.binding.run_id
    ):
        raise ManagementDeniedError("Coding immutable native C registration differs")
    end_us = await owner_locked(services, session, control, scope, owner, end_us)
    return CodingBundle(record, bound, native), end_us


async def static_read_locked(
    services: CodingServices,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    witness: AuthenticatedWorkerIdentity,
    binding: CurrentPlanBinding,
    action: ActionRecord,
    end_us: int,
) -> int:
    """Exact charter/target resources are checked separately from saved context contributors."""
    symbols = await action_resource_symbols(
        session, binding, action.proposal, services.management.catalog
    )
    refs, ids = await review_named_artifacts(
        session, binding, action.proposal, services.management.catalog, symbols
    )
    disclosure = await review_disclosure(
        session, control, scope, witness.identity, services.source_views, refs, ids
    )
    if disclosure is None:
        raise ManagementDeniedError("Coding static source READ is unavailable")
    before = clock_us()
    now = await db_clock(session)
    witness.require_time(now)
    windows = (witness.expires_at, *((disclosure.valid_until,) if disclosure.valid_until else ()))
    end_us = min(end_us, *(before + (end - now) // timedelta(microseconds=1) for end in windows))
    require_time(end_us)
    services.require_composition()
    return end_us
