"""Actual immutable ancestry must retain zero model allowance for native-only work."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.native_execution_profiles import native_execution_profile
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation
from nexus.company.notifications.native_profile_checks import native_notification_profile
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.harness.journal_models import CompanyControl


async def require_native_ancestry(
    session: AsyncSession,
    work: ExecutionWork,
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    *,
    control: CompanyControl | None = None,
    identity: VerifiedIdentity | None = None,
) -> None:
    """Read actual parents under the company mutex; names cannot replace registered quota."""
    if native_execution_profile(catalog, child) is None:
        return
    if catalog.cycle_admission is not None:
        from nexus.execution.cycle_partition_checks import require_cycle_native_partition

        admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
        if (
            admission is None
            or control is None
            or identity is None
            or child not in tuple(slot.child for slot in admission.slots[2:4])
        ):
            raise ExecutionDeniedError("Selected native ancestry needs its actual current actor")
        await require_cycle_native_partition(
            session, control, work, identity, admission=admission, registry=catalog.models
        )
        return
    await require_zero_model_ancestry(session, work)


async def require_notification_ancestry(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
    *,
    identity: VerifiedIdentity | None = None,
) -> None:
    """Actual owner sender and immutable zero-model ancestors, without granting a permit."""
    if native_notification_profile(catalog, child) is None:
        return
    if work.actor_id != control.owner_id:
        raise ExecutionDeniedError("Native notification sender differs from the actual owner")
    if catalog.cycle_admission is not None:
        from nexus.execution.cycle_partition_checks import require_cycle_native_partition

        admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
        if (
            admission is None
            or identity is None
            or identity.principal_id != control.owner_id
            or child != admission.slots[-1].child
        ):
            raise ExecutionDeniedError("Mixed sender ancestry requires its actual current owner")
        await require_cycle_native_partition(
            session, control, work, identity, admission=admission, registry=catalog.models
        )
        return
    await require_zero_model_ancestry(session, work)


async def require_zero_model_ancestry(session: AsyncSession, work: ExecutionWork) -> None:
    """Check every actual immutable ancestor under the caller's company transaction."""
    current, visited = work, set[UUID]()
    while True:
        if current.task_id in visited or len(visited) >= 101:
            raise ExecutionDeniedError("Native ancestry is cyclic or exceeds its bound")
        visited.add(current.task_id)
        registration = snapshot(current).registration
        if (
            registration_digest(registration) != current.registration_hash
            or registration.quota.model_requests != 0
            or (
                current.model_requests_limit,
                current.model_requests_used,
                current.model_requests_delegated,
            )
            != (0, 0, 0)
        ):
            raise ExecutionDeniedError("Native ancestor model allowance or registration differs")
        if current.parent_task_id is None:
            return
        parent = await session.get(ExecutionWork, (work.company_id, current.parent_task_id))
        if parent is None or parent.company_id != work.company_id:
            raise ExecutionDeniedError("Native registered ancestor is unavailable")
        current = parent
