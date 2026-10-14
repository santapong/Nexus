"""Current signed registered-verifier target read without manufacturing execution capacity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_support import resolve_work_target
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_input_contracts import native_author
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_support import db_now, execution_row, require_runtime_scope
from nexus.harness.journal_models import CompanyControl


async def read_registered_verification_target(
    session: AsyncSession,
    control: CompanyControl,
    binding: RunBinding,
    identity: VerifiedIdentity,
    author_action_id: UUID,
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> VerificationSpec:
    """Read actual current work/author receipt/protected refs; no lease, hold or permit results."""
    binding = RunBinding.model_validate_json(binding.model_dump_json())
    if not session.in_transaction() or control.company_id != binding.company_id:
        raise ManagementDeniedError("Registered target read requires its actual company mutex")
    row = await execution_row(session, ledger_scope(binding))
    if native_author(row)[0] != binding or (identity.principal_id, identity.workspace_id) != (
        binding.actor_id,
        binding.workspace_id,
    ):
        raise ManagementDeniedError("Registered verifier target differs from exact signed work")
    await require_runtime_scope(
        session, control, ledger_scope(binding), identity, allow_inactive=False, owner_read=False
    )
    await require_management_execution(
        session, control, row, identity, catalog, artifacts, freshness
    )
    target = await resolve_work_target(session, control, binding, row, author_action_id)
    scope = BrainReadScope(
        company_id=binding.company_id,
        workspace_id=binding.workspace_id,
        principal_id=binding.actor_id,
        operation_id=author_action_id,
        trace_id=binding.trace_id,
        task_id=binding.task_id,
        task_trace_id=binding.trace_id,
        actor_id=binding.actor_id,
    )
    for reference in target.artifacts:
        await artifacts.revalidate_artifact_reference(
            session, control, scope, identity, reference, await db_now(session)
        )
    await freshness.revalidate_references(session, scope, target.artifacts, await db_now(session))
    return target
