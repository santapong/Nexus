"""Same-session parent-first native registration never activates a worker or refunds slices."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_contracts import WorkRegistration
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.governance import CharterRevision
from nexus.company.management.plan_models import (
    ManagementPlanDependency,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementVerificationBinding,
)
from nexus.company.management.plans import ChildAllocation, PlanPayload, RunBinding
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_registration import register_locked
from nexus.execution.runtime_support import registration_digest


def registration(binding: RunBinding, item: WorkItem, quota: AttemptQuota) -> ExecutionRegistration:
    """Retain the exact existing M1 normalized immutable application contract."""
    return ExecutionRegistration(
        work=item,
        run_id=binding.run_id,
        workflow_name=binding.workflow_name,
        workflow_version=binding.workflow_version,
        model_profile=binding.model_profile,
        model_registry_version=binding.model_registry_version,
        quota=quota,
    )


async def _register(
    session: AsyncSession,
    directory: PersistentCompanyDirectory,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    binding: RunBinding,
    item: WorkItem,
    quota: AttemptQuota,
    parent: UUID | None,
    principals: tuple[UUID, ...],
) -> str:
    await directory.register_work_in_transaction(
        session,
        WorkRegistration(
            company_id=scope.company_id,
            workspace_id=binding.workspace_id,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
            actor_id=binding.actor_id,
            parent_task_id=parent,
            allocation_usd=item.budget_usd,
            allowed_principals=principals,
        ),
        scope,
        identity,
    )
    actual = await session.get(RegisteredWork, (scope.company_id, binding.task_id))
    if actual is None or not actual.active:
        raise ManagementDeniedError("Actual registered plan work is unavailable")
    expected = registration(binding, item, quota)
    existing = await session.get(ExecutionWork, (scope.company_id, binding.task_id))
    if existing is not None:
        stored = ExecutionRegistration.model_validate_json(existing.registration_json)
        if stored != expected or registration_digest(stored) != existing.registration_hash:
            raise ManagementDeniedError(
                "Existing child immutable registration differs from the plan"
            )
        # Equal Decimal values may have a different display scale. Preserve the
        # original M1 byte recipe/hash without rewriting its immutable contract.
        expected = stored
    row = await register_locked(session, expected, actual)
    return row.registration_hash


async def ensure_procedure(
    session: AsyncSession,
    directory: PersistentCompanyDirectory,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    now: datetime,
) -> ManagementProcedure:
    """One permanent goal root survives plan IDs/revisions with identical USD/quota/run pins."""
    # Keep the >50-line exact root comparison, M1 registration and native FK insert together.
    root = payload.procedure
    existing = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == scope.company_id,
            ManagementProcedure.goal_id == root.goal_id,
        )
    )
    if existing is not None and (
        existing.procedure_id,
        existing.parent_task_id,
        existing.parent_run_id,
        existing.allocation_usd,
        AttemptQuota.model_validate_json(existing.quota_json),
        RunBinding.model_validate_json(existing.binding_json),
    ) != (
        root.procedure_id,
        root.binding.task_id,
        root.binding.run_id,
        root.allocation_usd,
        root.quota,
        root.binding,
    ):
        raise ManagementDeniedError(
            "A goal procedure root cannot be replaced or replenish allowance"
        )
    item = WorkItem(
        company_id=scope.company_id,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    await _register(
        session,
        directory,
        scope,
        identity,
        root.binding,
        item,
        root.quota,
        None,
        (root.binding.actor_id,),
    )
    if existing is None:
        existing = ManagementProcedure(
            company_id=scope.company_id,
            procedure_id=root.procedure_id,
            goal_id=root.goal_id,
            parent_task_id=root.binding.task_id,
            parent_run_id=root.binding.run_id,
            allocation_usd=root.allocation_usd,
            quota_json=root.quota.model_dump_json(),
            binding_json=root.binding.model_dump_json(by_alias=True),
            recorded_at=now,
        )
        session.add(existing)
        await session.flush()
    return existing


async def register_children(
    session: AsyncSession,
    directory: PersistentCompanyDirectory,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    payload: PlanPayload,
    revision_id: UUID,
    charters: dict[UUID, CharterRevision],
) -> None:
    """Any later item failure rolls back every native child and permanently delegated slice."""
    # This >50-line batch retains parent/child/edge writes in one transaction-owned sequence.
    items = {row.task_id: row for row in payload.plan.items}
    for child in payload.children:
        charter = charters[child.charter.revision_id]
        work_hash = await _register(
            session,
            directory,
            scope,
            identity,
            child.binding,
            items[child.binding.task_id],
            child.quota,
            payload.procedure.binding.task_id,
            tuple(sorted({child.binding.actor_id, charter.charter.verifier_id})),
        )
        session.add(
            ManagementPlanTask(
                company_id=scope.company_id,
                plan_revision_id=revision_id,
                task_id=child.binding.task_id,
                run_id=child.binding.run_id,
                goal_id=payload.goal.goal_id,
                procedure_id=payload.procedure.procedure_id,
                department_id=child.charter.department_id,
                charter_revision_id=child.charter.revision_id,
                allocation_usd=child.allocation_usd,
                quota_json=child.quota.model_dump_json(),
                binding_json=child.binding.model_dump_json(by_alias=True),
                work_sha256=work_hash,
            )
        )
    await session.flush()

    for item in payload.plan.items:
        for dependency in item.depends_on:
            session.add(
                ManagementPlanDependency(
                    company_id=scope.company_id,
                    plan_revision_id=revision_id,
                    task_id=item.task_id,
                    dependency_task_id=dependency,
                )
            )
    for edge in payload.verification:
        session.add(
            ManagementVerificationBinding(
                company_id=scope.company_id,
                plan_revision_id=revision_id,
                verifier_task_id=edge.verifier_task_id,
                author_task_id=edge.author_task_id,
                check_recipe=edge.check_recipe,
            )
        )
    await session.flush()


def require_native_task(
    row: ManagementPlanTask,
    execution: ExecutionWork,
    child: ChildAllocation,
    payload: PlanPayload,
) -> None:
    """Compare exact immutable task/quota/charter/root data before projecting a current binding."""
    if (
        RunBinding.model_validate_json(row.binding_json),
        AttemptQuota.model_validate_json(row.quota_json),
        row.run_id,
        row.goal_id,
        row.procedure_id,
        row.department_id,
        row.charter_revision_id,
        row.allocation_usd,
        row.work_sha256,
    ) != (
        child.binding,
        child.quota,
        child.binding.run_id,
        payload.goal.goal_id,
        payload.procedure.procedure_id,
        child.charter.department_id,
        child.charter.revision_id,
        child.allocation_usd,
        execution.registration_hash,
    ):
        raise ManagementDeniedError("Native managed task differs from the approved exact payload")
