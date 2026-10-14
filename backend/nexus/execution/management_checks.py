"""Fresh native management gates under CompanyControl; only supplied-session DB reads.

The file slightly exceeds 400 lines to keep the public acceptance reader and the
same exact dependency/verification/effect gate adjacent, without duplicated logic.
"""

from __future__ import annotations

from uuid import UUID, uuid5

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.acceptance_support import actual_receipt, receipt_artifacts
from nexus.company.management.cancellation_support import require_not_cancelled
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock, require_member
from nexus.company.management.plan_models import (
    ManagementPlanDependency,
    ManagementPlanRevision,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import (
    PlanAdmissionCatalog,
    validate_plan,
    validate_plan_action,
)
from nexus.company.management.plan_support import PlanSourceFreshness as ManagementArtifactFreshness
from nexus.company.management.plans import RunBinding, VerificationIntent
from nexus.company.management.revision_store import plan_record, require_current_governance
from nexus.execution.runtime_contracts import AttemptKind, ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.harness.journal_models import CompanyControl

logger = structlog.get_logger()
__all__ = ["ManagementArtifactFreshness", "current_accepted_work", "require_management_execution"]


async def _readable(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    artifact: BrainArtifactRevision,
    artifacts: BoundedArtifactReader | None,
    freshness: ManagementArtifactFreshness | None,
) -> None:
    if artifacts is None or freshness is None:
        raise ExecutionDeniedError("Complete management artifact revalidation is not configured")
    scope = BrainReadScope(
        company_id=work.company_id,
        workspace_id=work.workspace_id,
        principal_id=identity.principal_id,
        operation_id=uuid5(work.task_id, "management-artifact-check"),
        trace_id=work.trace_id,
        task_id=work.task_id,
        task_trace_id=work.trace_id,
        actor_id=work.actor_id,
    )
    reference = ArtifactRevisionRef(
        company_id=artifact.company_id,
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.artifact_revision_id,
        revision=artifact.revision,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
    )
    await artifacts.revalidate_artifact_reference(
        session, control, scope, identity, reference, await db_clock(session)
    )
    await freshness.revalidate_references(session, scope, (reference,), await db_clock(session))


async def _accepted(
    session: AsyncSession,
    control: CompanyControl,
    reader: ExecutionWork,
    dependency: ExecutionWork,
    identity: VerifiedIdentity,
    artifacts: BoundedArtifactReader | None,
    freshness: ManagementArtifactFreshness | None,
) -> WorkAcceptance:
    # Keep the >50-line exact acceptance/receipt/native proof comparison in one read-only gate.
    row = await session.scalar(
        select(ManagementWorkAcceptance)
        .where(
            ManagementWorkAcceptance.company_id == dependency.company_id,
            ManagementWorkAcceptance.author_task_id == dependency.task_id,
            ManagementWorkAcceptance.author_run_id == dependency.run_id,
        )
        .order_by(
            ManagementWorkAcceptance.recorded_at.desc(),
            ManagementWorkAcceptance.acceptance_id.desc(),
        )
        .limit(1)
    )
    if row is None:
        raise ExecutionDeniedError("Management dependency is independently unaccepted")
    result = acceptance_record(row)
    target = result.target
    author_binding = await ManagementPlanStore.current_binding(
        session, dependency.company_id, dependency.task_id
    )
    verifier_binding = await ManagementPlanStore.current_binding(
        session, dependency.company_id, target.verifier.task_id
    )
    if (
        author_binding is None
        or verifier_binding is None
        or (
            author_binding.child.binding != target.author
            or verifier_binding.child.binding != target.verifier
            or registration_digest(snapshot(dependency).registration)
            != dependency.registration_hash
        )
    ):
        raise ExecutionDeniedError("Dependency acceptance author/verifier binding is not current")
    await require_current_governance(session, control, author_binding.plan, author_binding.child)
    await require_current_governance(
        session, control, verifier_binding.plan, verifier_binding.child
    )
    invalidation = await session.scalar(
        select(ManagementAcceptanceInvalidation.invalidation_id)
        .where(
            ManagementAcceptanceInvalidation.company_id == dependency.company_id,
            ManagementAcceptanceInvalidation.acceptance_id == result.acceptance_id,
        )
        .limit(1)
    )
    if (
        result.verdict != "pass"
        or invalidation is not None
        or target.work_snapshot_sha256 != dependency.registration_hash
        or target.criterion_ids != snapshot(dependency).registration.work.acceptance
    ):
        raise ExecutionDeniedError("Management dependency acceptance is invalidated or stale")
    receipt = await actual_receipt(session, dependency, target.action_id)
    if (
        canonical_sha256(receipt) != target.receipt_sha256
        or receipt.receipt_id != target.receipt_id
        or await receipt_artifacts(session, receipt) != target.artifacts
    ):
        raise ExecutionDeniedError("Management acceptance binds another issued result")
    await require_member(session, control, target.verifier.actor_id)
    for reference in target.artifacts:
        output = await session.get(
            BrainArtifactRevision, (dependency.company_id, reference.artifact_revision_id)
        )
        if output is None:
            raise ExecutionDeniedError("Accepted dependency output is unavailable")
        await _readable(session, control, reader, identity, output, artifacts, freshness)
    proof_rows = (
        await session.scalars(
            select(ManagementAcceptanceProof).where(
                ManagementAcceptanceProof.company_id == dependency.company_id,
                ManagementAcceptanceProof.acceptance_id == result.acceptance_id,
            )
        )
    ).all()
    if len(proof_rows) != len(result.proofs):
        raise ExecutionDeniedError("Management dependency lacks complete protected proof")
    for proof in result.proofs:
        native = next((item for item in proof_rows if item.proof_id == proof.proof_id), None)
        artifact = await session.get(
            BrainArtifactRevision,
            (dependency.company_id, proof.result_artifact.artifact_revision_id),
        )
        if (
            native is None
            or artifact is None
            or native.proof_json != proof.model_dump_json()
            or native.target_sha256 != canonical_sha256(target)
            or native.artifact_revision_id != proof.result_artifact.artifact_revision_id
            or native.artifact_sha256 != proof.result_artifact.sha256
            or native.check_recipe != proof.recipe
            or artifact.artifact_id != proof.result_artifact.artifact_id
            or artifact.revision != proof.result_artifact.revision
            or artifact.sha256 != proof.result_artifact.sha256
            or artifact.byte_length != proof.result_artifact.byte_length
        ):
            raise ExecutionDeniedError("Management dependency proof hash/binding is unavailable")
        await _readable(session, control, reader, identity, artifact, artifacts, freshness)
    return result


async def current_accepted_work(
    session: AsyncSession,
    control: CompanyControl,
    reader: ExecutionWork,
    dependency: ExecutionWork,
    identity: VerifiedIdentity,
    artifacts: BoundedArtifactReader,
    freshness: ManagementArtifactFreshness,
) -> WorkAcceptance | None:
    """Read current independent acceptance under the company mutex; return no execution permit."""
    if (
        not session.in_transaction()
        or control.company_id != reader.company_id
        or reader.company_id != dependency.company_id
    ):
        raise ExecutionDeniedError("Acceptance read requires the actual company transaction")
    try:
        return await _accepted(session, control, reader, dependency, identity, artifacts, freshness)
    except ValueError as exc:
        logger.bind(task_id=str(reader.task_id), trace_id=str(reader.trace_id)).debug(
            "management_acceptance_not_current", error_type=type(exc).__name__
        )
        return None


async def _dependencies(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    revision_id: UUID,
    identity: VerifiedIdentity,
    artifacts: BoundedArtifactReader | None,
    freshness: ManagementArtifactFreshness | None,
    expected: tuple[UUID, ...],
) -> None:
    rows = (
        await session.scalars(
            select(ManagementPlanDependency).where(
                ManagementPlanDependency.company_id == work.company_id,
                ManagementPlanDependency.plan_revision_id == revision_id,
                ManagementPlanDependency.task_id == work.task_id,
            )
        )
    ).all()
    if {edge.dependency_task_id for edge in rows} != set(expected):
        raise ExecutionDeniedError("Native management dependencies differ from the approved plan")
    for edge in rows:
        dependency = await session.get(ExecutionWork, (work.company_id, edge.dependency_task_id))
        if dependency is None:
            raise ExecutionDeniedError("Management dependency registration is unavailable")
        await _accepted(session, control, work, dependency, identity, artifacts, freshness)


async def _verification_trigger(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    revision_id: UUID,
    identity: VerifiedIdentity,
    reader: BoundedArtifactReader | None,
    freshness: ManagementArtifactFreshness | None,
    expected: VerificationIntent | None,
) -> None:
    edge = await session.get(
        ManagementVerificationBinding, (work.company_id, revision_id, work.task_id)
    )
    if edge is None and expected is None:
        return
    if (
        edge is None
        or expected is None
        or (edge.author_task_id, edge.verifier_task_id, edge.check_recipe)
        != (expected.author_task_id, expected.verifier_task_id, expected.check_recipe)
    ):
        raise ExecutionDeniedError("Native verification trigger differs from the approved plan")
    author = await session.get(ExecutionWork, (work.company_id, edge.author_task_id))
    if author is None:
        raise ExecutionDeniedError("Verification author is unavailable")
    effect = await session.scalar(
        select(EffectIntent)
        .where(
            EffectIntent.company_id == work.company_id,
            EffectIntent.task_id == author.task_id,
            EffectIntent.run_id == author.run_id,
            EffectIntent.state == "succeeded",
        )
        .order_by(EffectIntent.created_at.desc(), EffectIntent.action_id.desc())
        .limit(1)
    )
    if effect is None:
        raise ExecutionDeniedError("Verification awaits an exact issued result")
    receipt = await actual_receipt(session, author, effect.action_id)
    artifacts = await receipt_artifacts(session, receipt)
    for ref in artifacts:
        artifact = await session.get(
            BrainArtifactRevision, (work.company_id, ref.artifact_revision_id)
        )
        if artifact is None:
            raise ExecutionDeniedError("Verification protected output is unavailable")
        await _readable(session, control, work, identity, artifact, reader, freshness)


async def require_management_execution(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    catalog: PlanAdmissionCatalog | None,
    artifacts: BoundedArtifactReader | None = None,
    freshness: ManagementArtifactFreshness | None = None,
    proposal: ActionProposal | None = None,
    kind: AttemptKind | None = None,
) -> None:
    """Recheck at execute claim and after preparation immediately before fresh intent.

    Old profiles without management tables contain no managed native rows. Issued
    receipt/unknown reconciliation does not call this new-execution gate.
    """
    await require_not_cancelled(session, work.company_id, work.task_id)
    # Keep legacy discrimination, exact work and every prerequisite in this >50-line gate.
    if (
        await session.scalar(select(func.to_regclass("public.company_management_procedures")))
        is None
    ):
        if (
            await session.scalar(select(func.to_regclass("public.company_management_plan_tasks")))
            is not None
        ):
            raise ExecutionDeniedError("Management schema is incomplete")
        return
    management_kind = await ManagementPlanStore.managed_kind(session, work.company_id, work.task_id)
    if management_kind == "unmanaged":
        return
    if management_kind == "procedure" or catalog is None:
        raise ExecutionDeniedError(
            "Managed execution requires an admitted child and server catalog"
        )
    binding = await ManagementPlanStore.current_binding(session, work.company_id, work.task_id)
    if binding is None or binding.child.binding.actor_id != identity.principal_id:
        raise ExecutionDeniedError("Managed work has no current approved exact actor binding")
    native = await session.get(
        ManagementPlanRevision, (work.company_id, binding.plan.plan_revision_id)
    )
    if native is None:
        raise ExecutionDeniedError("Managed plan is unavailable")
    record = plan_record(native)
    expected = registration(binding.child.binding, binding.work, binding.child.quota)
    actual_binding = RunBinding(
        company_id=work.company_id,
        workspace_id=work.workspace_id,
        actor_id=work.actor_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        run_id=work.run_id,
        workflow_name=work.workflow_name,
        workflow_version=work.workflow_version,
        model_profile=work.model_profile,
        model_registry_version=work.model_registry_version,
    )
    if (
        actual_binding != binding.child.binding
        or snapshot(work).registration != expected
        or registration_digest(snapshot(work).registration) != work.registration_hash
        or binding.work_sha256 != work.registration_hash
    ):
        raise ExecutionDeniedError("Managed work registration hash/criteria/version differs")
    scope = CompanyControlScope(
        company_id=work.company_id,
        principal_id=identity.principal_id,
        operation_id=uuid5(work.task_id, "management-execution-check"),
        trace_id=work.trace_id,
    )
    try:
        charters = await validate_plan(
            session, control, scope, identity, record.payload, catalog, freshness
        )
        if proposal is not None:
            if kind is None:
                raise ExecutionDeniedError("Managed effect attempt kind is unavailable")
            validate_plan_action(
                catalog,
                binding.child,
                charters[binding.child.charter.revision_id],
                proposal,
                kind,
                await db_clock(session),
            )
        await _dependencies(
            session,
            control,
            work,
            record.plan_revision_id,
            identity,
            artifacts,
            freshness,
            binding.work.depends_on,
        )
        trigger = next(
            (edge for edge in record.payload.verification if edge.verifier_task_id == work.task_id),
            None,
        )
        await _verification_trigger(
            session, control, work, record.plan_revision_id, identity, artifacts, freshness, trigger
        )
    except ValueError as exc:
        raise ExecutionDeniedError("Current management execution evidence is unavailable") from exc
