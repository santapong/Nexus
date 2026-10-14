"""Reconcile-only current engineering pair resolution cannot grant a fresh native effect."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
from nexus.builder.engineering_pair_selection import EngineeringPairSelection, resolve_pair
from nexus.company.access import VerifiedIdentity
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, require_lease
from nexus.harness.journal_models import CompanyControl


async def resolve_recovery_target(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    *,
    verifier_action_id: UUID,
    catalog: PlanAdmissionCatalog,
    inputs: RegisteredEngineeringInputs,
) -> EngineeringPairSelection:
    """Current native records, active scope and reconciliation fence precede protected reads."""
    work = await execution_row(session, lease_scope(lease))
    require_lease(work, lease, await db_now(session))
    require_acceptance(lease.mode == "reconcile" and not control.paused)
    await require_management_execution(
        session,
        control,
        work,
        identity,
        catalog,
        inputs.reader,
        inputs.freshness,
    )
    pair = await resolve_pair(session, control, lease, verifier_action_id=verifier_action_id)
    require_acceptance(pair.target.verifier.task_id == work.task_id)
    require_lease(work, lease, await db_now(session))
    return pair
