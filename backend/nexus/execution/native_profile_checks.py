"""Actual immutable ancestry must retain zero model allowance for native-only work."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.native_execution_profiles import native_execution_profile
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot


async def require_native_ancestry(
    session: AsyncSession,
    work: ExecutionWork,
    catalog: PlanAdmissionCatalog,
    child: ChildAllocation,
) -> None:
    """Read actual parents under the company mutex; names cannot replace registered quota."""
    if native_execution_profile(catalog, child) is None:
        return
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
