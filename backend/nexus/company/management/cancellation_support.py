"""Bounded actual native ancestry reads; permanent stop is never inferred from activity."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cancellation_contracts import InheritedCancellation, OwnerCancellation
from nexus.company.management.cancellation_models import WorkCancellation
from nexus.company.management.plan_models import ManagementProcedure
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot


class WorkCancelledError(ExecutionDeniedError):
    """Actual task/ancestor owner cancellation permanently forbids new execution."""


def cancellation_record(row: WorkCancellation) -> OwnerCancellation:
    """Decode native immutable facts, including exact command/audit identities."""
    target = RunBinding.model_validate_json(row.binding_json)
    if (target.company_id, target.task_id, target.trace_id, target.run_id) != (
        row.company_id,
        row.task_id,
        row.trace_id,
        row.run_id,
    ):
        raise WorkCancelledError("Native cancellation binding is inconsistent")
    return OwnerCancellation(
        company_id=row.company_id,
        cancellation_id=row.cancellation_id,
        target=target,
        registration_sha256=row.registration_sha256,
        reason=row.reason,
        owner_id=row.owner_id,
        operation_id=row.operation_id,
        audit_trace_id=row.audit_trace_id,
        recorded_at=row.recorded_at,
    )


def actual_binding(row: ExecutionWork) -> RunBinding:
    """Use exact actual M1 columns; no requester-chosen run/actor/workspace can replace them."""
    if registration_digest(snapshot(row).registration) != row.registration_hash:
        raise WorkCancelledError("Native work registration hash is unavailable")
    return RunBinding(
        company_id=row.company_id,
        workspace_id=row.workspace_id,
        actor_id=row.actor_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        run_id=row.run_id,
        workflow_name=row.workflow_name,
        workflow_version=row.workflow_version,
        model_profile=row.model_profile,
        model_registry_version=row.model_registry_version,
    )


# Keep this bounded >50-line read together: complete native ancestry precedes
# closest-ancestor selection, and any inconsistent chain must fail closed.
async def cancellation_for_work(
    session: AsyncSession,
    company_id: UUID,
    task_id: UUID,
    *,
    trace_id: UUID | None = None,
    run_id: UUID | None = None,
) -> InheritedCancellation | None:
    """Read closest explicit cancellation in actual immutable ancestry under the caller's scope.

    Earlier unmanaged profiles lack this additive table and retain their old read
    paths. Registered work is mandatory when the table exists; malformed/missing
    ancestry denies rather than guessing an uncancelled task.
    """
    if (
        await session.scalar(select(func.to_regclass("public.company_management_cancellations")))
        is None
    ):
        return None
    current = await session.get(RegisteredWork, (company_id, task_id))
    execution = await session.get(ExecutionWork, (company_id, task_id))
    if (
        current is None
        or (trace_id is not None and current.trace_id != trace_id)
        or (run_id is not None and (execution is None or execution.run_id != run_id))
    ):
        raise WorkCancelledError("Exact cancellation lookup work is unavailable")
    chain: list[RegisteredWork] = []
    seen: set[UUID] = set()
    for _ in range(16):
        if current.task_id in seen:
            raise WorkCancelledError("Cancellation ancestry is cyclic")
        seen.add(current.task_id)
        chain.append(current)
        if current.parent_task_id is None:
            if current.root_task_id != current.task_id:
                raise WorkCancelledError("Cancellation root identity is inconsistent")
            break
        parent = await session.get(RegisteredWork, (company_id, current.parent_task_id))
        if parent is None or (parent.root_task_id, parent.workspace_id) != (
            current.root_task_id,
            current.workspace_id,
        ):
            raise WorkCancelledError("Cancellation ancestry is incomplete")
        current = parent
    else:
        raise WorkCancelledError("Cancellation ancestry exceeds the admitted bound")
    for ancestor in chain:
        row = await session.scalar(
            select(WorkCancellation)
            .where(
                WorkCancellation.company_id == company_id,
                WorkCancellation.task_id == ancestor.task_id,
            )
            .order_by(WorkCancellation.recorded_at, WorkCancellation.cancellation_id)
            .limit(1)
        )
        if row is not None:
            record = cancellation_record(row)
            actual = await session.get(ExecutionWork, (company_id, ancestor.task_id))
            if (
                actual is None
                or actual_binding(actual) != record.target
                or actual.registration_hash != record.registration_sha256
            ):
                raise WorkCancelledError("Native cancellation target no longer matches exact work")
            return InheritedCancellation(
                company_id=company_id,
                requested_task_id=task_id,
                ancestor_task_id=ancestor.task_id,
                inherited=ancestor.task_id != task_id,
                cancellation=record,
            )
    return None


async def require_not_cancelled(session: AsyncSession, company_id: UUID, task_id: UUID) -> None:
    """Stop new effects/claims/admission while leaving issued facts and ledgers untouched."""
    if await cancellation_for_work(session, company_id, task_id) is not None:
        raise WorkCancelledError("Owner cancelled this work or its actual registered ancestor")


async def require_plan_not_cancelled(
    session: AsyncSession, company_id: UUID, payload: PlanPayload
) -> None:
    """A stopped goal cannot substitute new root/run/child IDs through another plan."""
    procedure = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == company_id,
            ManagementProcedure.goal_id == payload.goal.goal_id,
        )
    )
    if procedure is not None:
        await require_not_cancelled(session, company_id, procedure.parent_task_id)
    for task_id in (
        payload.procedure.binding.task_id,
        *(child.binding.task_id for child in payload.children),
    ):
        if await session.get(RegisteredWork, (company_id, task_id)) is not None:
            await require_not_cancelled(session, company_id, task_id)
