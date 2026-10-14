"""Owner-selected existing native work and exact report author/verifier sharing bindings."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.operating_report_bindings import native_declarations
from nexus.company.management.operating_report_contracts import ReportSelection
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanRevision,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_inputs import native_author
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.execution.runtime_models import ExecutionWork


async def resolve_selection(
    session: AsyncSession,
    company_id: UUID,
    revision_id: UUID,
    author_task_id: UUID,
    selected_task_ids: tuple[UUID, ...],
) -> ReportSelection:
    require_acceptance(
        len(selected_task_ids) <= 100 and len(set(selected_task_ids)) == len(selected_task_ids)
    )
    row = await session.get(ManagementPlanRevision, (company_id, revision_id))
    require_acceptance(row is not None)
    assert row is not None
    plan = plan_record(row)
    bindings = (
        await session.scalars(
            select(ManagementVerificationBinding).where(
                ManagementVerificationBinding.company_id == company_id,
                ManagementVerificationBinding.plan_revision_id == revision_id,
                ManagementVerificationBinding.author_task_id == author_task_id,
            )
        )
    ).all()
    require_acceptance(len(bindings) == 1)
    edge = bindings[0]
    current = await ManagementPlanStore.current_binding(session, company_id, edge.verifier_task_id)
    require_acceptance(current is not None and current.plan.plan_revision_id == revision_id)
    allowed = {child.binding.task_id: child.binding for child in plan.payload.children}
    work = []
    for key in sorted(selected_task_ids):
        native = await session.get(ExecutionWork, (company_id, key))
        require_acceptance(native is not None)
        assert native is not None
        actual, _ = native_author(native)
        await require_registered_selection(session, native, actual)
        work.append(actual)
    return ReportSelection(
        company_id=company_id,
        plan=plan_reference(plan),
        author=allowed[author_task_id],
        verifier=allowed[edge.verifier_task_id],
        work=tuple(work),
    )


async def require_registered_selection(
    session: AsyncSession, native: ExecutionWork, binding: RunBinding
) -> None:
    declarations = await native_declarations(session, native.company_id, binding)
    matched = False
    for declaration in declarations:
        if declaration.task_id == native.task_id:
            require_acceptance(declaration.work_sha256 == native.registration_hash)
        approved = await session.scalar(
            select(ManagementOwnerDecision.decision_id)
            .where(
                ManagementOwnerDecision.company_id == native.company_id,
                ManagementOwnerDecision.plan_revision_id == declaration.plan_revision_id,
                ManagementOwnerDecision.kind == "approve",
            )
            .limit(1)
        )
        matched = matched or approved is not None
    require_acceptance(matched)
