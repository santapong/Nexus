"""Report selection sharing binds an exact current approved output, never a declared report ID."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_support import actual_receipt, receipt_artifacts
from nexus.company.management.operating_report_contracts import (
    ReportSelection,
    SavedOperatingReport,
)
from nexus.company.management.plan_models import ManagementVerificationBinding
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.report_inputs import native_author
from nexus.company.management.revision_store import require_current_governance
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def require_report_share(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    record: SavedOperatingReport,
    output: ArtifactRevisionRef,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> None:
    selection = record.selection
    require_acceptance(
        scope.task_id == selection.verifier.task_id
        and scope.actor_id == identity.principal_id
        and identity.principal_id == selection.verifier.actor_id
        and scope.task_trace_id == selection.verifier.trace_id
    )
    require_acceptance(scope.task_id is not None)
    assert scope.task_id is not None
    binding = await ManagementPlanStore.current_binding(session, scope.company_id, scope.task_id)
    author = await session.get(ExecutionWork, (scope.company_id, selection.author.task_id))
    require_acceptance(
        binding is not None
        and author is not None
        and binding.child.binding == selection.verifier
        and binding.plan == selection.plan
    )
    assert author is not None and binding is not None
    require_acceptance(native_author(author)[0] == selection.author)
    await require_current_governance(session, control, binding.plan, binding.child)
    edge = await session.get(
        ManagementVerificationBinding,
        (scope.company_id, selection.plan.plan_revision_id, selection.verifier.task_id),
    )
    require_acceptance(edge is not None and edge.author_task_id == selection.author.task_id)
    await exact_output_receipt(session, scope, selection, author, output)
    await artifacts.revalidate_artifact_reference(
        session, control, scope, identity, output, await db_now(session)
    )
    await freshness.revalidate_references(session, scope, (output,), await db_now(session))


async def exact_output_receipt(
    session: AsyncSession,
    scope: BrainReadScope,
    selection: ReportSelection,
    author: ExecutionWork,
    output: ArtifactRevisionRef,
) -> None:
    effects = (
        await session.scalars(
            select(EffectIntent).where(
                EffectIntent.company_id == scope.company_id,
                EffectIntent.task_id == selection.author.task_id,
                EffectIntent.run_id == selection.author.run_id,
                EffectIntent.state == "succeeded",
            )
        )
    ).all()
    require_acceptance(len(effects) <= 32)
    matching = []
    for effect in effects:
        receipt = await actual_receipt(session, author, effect.action_id)
        refs = await receipt_artifacts(session, receipt)
        if refs == (output,):
            matching.append(effect.action_id)
    require_acceptance(len(matching) == 1)
