"""Existing native child/procedure declarations resolve audit resource scopes without authority."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.plan_models import ManagementPlanTask, ManagementProcedure
from nexus.company.management.plans import RunBinding


async def native_declarations(
    session: AsyncSession,
    company_id: UUID,
    binding: RunBinding,
) -> tuple[ManagementPlanTask, ...]:
    direct = (
        await session.scalars(
            select(ManagementPlanTask).where(
                ManagementPlanTask.company_id == company_id,
                ManagementPlanTask.task_id == binding.task_id,
            )
        )
    ).all()
    if direct:
        require_acceptance(len(direct) <= 100)
        require_acceptance(
            all(RunBinding.model_validate_json(row.binding_json) == binding for row in direct)
        )
        return tuple(direct)
    root = await session.scalar(
        select(ManagementProcedure).where(
            ManagementProcedure.company_id == company_id,
            ManagementProcedure.parent_task_id == binding.task_id,
        )
    )
    require_acceptance(root is not None)
    assert root is not None
    require_acceptance(RunBinding.model_validate_json(root.binding_json) == binding)
    children = (
        await session.scalars(
            select(ManagementPlanTask).where(
                ManagementPlanTask.company_id == company_id,
                ManagementPlanTask.procedure_id == root.procedure_id,
            )
        )
    ).all()
    require_acceptance(0 < len(children) <= 1000)
    return tuple(children)
