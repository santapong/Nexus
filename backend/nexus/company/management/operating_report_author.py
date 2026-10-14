"""Actual current author read scope for preparing a saved report; never an issuance permit."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import revalidate_brain_scope
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.report_inputs import native_author
from nexus.company.management.revision_store import require_current_governance
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


async def require_report_author(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    record: SavedOperatingReport,
) -> None:
    author = record.selection.author
    require_acceptance(
        record.created_by == control.owner_id
        and scope.task_id == author.task_id
        and scope.actor_id == author.actor_id == identity.principal_id
        and scope.task_trace_id == author.trace_id
    )
    await revalidate_brain_scope(session, control, scope, identity)
    binding = await ManagementPlanStore.current_binding(session, scope.company_id, author.task_id)
    native = await session.get(ExecutionWork, (scope.company_id, author.task_id))
    require_acceptance(
        binding is not None
        and native is not None
        and binding.child.binding == author
        and binding.plan == record.selection.plan
    )
    assert binding is not None and native is not None
    require_acceptance(native_author(native)[0] == author)
    await require_current_governance(session, control, binding.plan, binding.child)
