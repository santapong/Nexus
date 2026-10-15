"""Actual read-only E/EV issuance and acceptance, under the P/C reader's own scope."""

import json
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_contracts import ENGINEERING_CRITERIA, ENGINEERING_RECIPE
from nexus.builder.engineering_metadata import actual_engineering_metadata
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.publication_support import require_replay_manifest
from nexus.builder.source_guard import RegisteredBuilderSource
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import BrainDerivation, BrainDerivationEvidence
from nexus.company.brain.retrieval_records import contributors
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef, SourceRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.native_contracts import (
    EngineeringIssuance,
    EngineeringPrerequisiteFacts,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.acceptance_provenance import (
    artifact_roots,
    exact_artifact,
    reference_sources,
)
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.management.acceptance_targets import current_work
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.cycle_deliverable_partition import require_cycle_deliverable_partition_locked
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


async def unique_issued_action(session: AsyncSession, work: ExecutionWork) -> UUID:
    rows = tuple(
        (
            await session.scalars(
                select(EffectIntent.action_id)
                .where(
                    EffectIntent.company_id == work.company_id,
                    EffectIntent.task_id == work.task_id,
                    EffectIntent.trace_id == work.trace_id,
                    EffectIntent.run_id == work.run_id,
                )
                .limit(2)
            )
        ).all()
    )
    require_acceptance(len(rows) == 1)
    return rows[0]


async def _issued(
    session: AsyncSession,
    work: ExecutionWork,
    action_id: UUID,
) -> tuple[BuilderExecutionSpec, ActionReceipt, EngineeringIssuance]:
    row = await session.get(JournalAction, action_id)
    effect = await session.get(EffectIntent, (work.company_id, action_id))
    attempt = await session.get(ExecutionAttempt, (work.company_id, work.task_id, action_id))
    require_acceptance(row is not None and effect is not None and attempt is not None)
    assert row is not None and effect is not None and attempt is not None
    limits = (work.tool_attempts_limit, work.tool_attempts_used, work.tool_attempts_delegated)
    require_acceptance(all(type(value) is int for value in limits) and limits == (1, 1, 0))
    action = ActionProposal.model_validate_json(row.proposal_json)
    spec = BuilderExecutionSpec.model_validate_json(json.dumps(action.parameters, allow_nan=False))
    require_acceptance(
        row.state == "authorized"
        and row.consumed_at is not None
        and row.company_id == action.company_id == work.company_id
        and (row.id, row.task_id, row.trace_id, row.proposal_hash)
        == (action_id, work.task_id, work.trace_id, action_hash(action))
        and (action.action_id, action.task_id, action.trace_id)
        == (action_id, work.task_id, work.trace_id)
        and action.resource == spec.job.resource_symbol
        and (action.tool, action.tool_version, action.actor_id)
        == ("company.builder.run.v1", "v1", work.actor_id)
        and (
            spec.job.company_id,
            spec.job.task_id,
            spec.job.trace_id,
            spec.job.run_id,
            spec.job.workspace_id,
            spec.job.actor_id,
            spec.job.action_id,
        )
        == (
            work.company_id,
            work.task_id,
            work.trace_id,
            work.run_id,
            work.workspace_id,
            work.actor_id,
            action_id,
        )
        and effect.company_id == attempt.company_id == work.company_id
        and effect.action_id == action_id
        and effect.state == "succeeded"
        and effect.attempt_kind == "tool_attempts"
        and type(effect.intent_fence) is type(work.fence) is int
        and 0 < effect.intent_fence <= work.fence
        and (effect.task_id, effect.trace_id, effect.run_id, effect.proposal_hash)
        == (work.task_id, work.trace_id, work.run_id, action_hash(action))
        and (attempt.task_id, attempt.trace_id, attempt.attempt_id, attempt.kind, attempt.fence)
        == (work.task_id, work.trace_id, action_id, "tool_attempts", effect.intent_fence)
        and row.consumed_at <= attempt.reserved_at <= effect.created_at
    )
    receipt = await actual_receipt(session, work, action_id)
    require_acceptance(effect.created_at <= receipt.recorded_at <= await db_now(session))
    assert row.consumed_at is not None
    return (
        spec,
        receipt,
        EngineeringIssuance(
            action,
            effect.intent_fence,
            row.consumed_at,
            attempt.reserved_at,
            effect.created_at,
            receipt,
        ),
    )


async def _reference(session: AsyncSession, receipt: ActionReceipt) -> ArtifactRevisionRef:
    require_acceptance(len(receipt.artifacts) == 1)
    ref = receipt.artifacts[0]
    require_acceptance(ref.company_id == receipt.company_id)
    row = (
        await session.execute(
            select(
                BrainArtifactRevision.artifact_revision_id,
                BrainArtifactRevision.sha256,
                BrainArtifactRevision.byte_length,
            ).where(
                BrainArtifactRevision.company_id == receipt.company_id,
                BrainArtifactRevision.artifact_id == ref.artifact_id,
                BrainArtifactRevision.revision == ref.revision,
            )
        )
    ).one_or_none()
    require_acceptance(row is not None and row[1] == ref.sha256)
    assert row is not None
    return ArtifactRevisionRef(
        company_id=receipt.company_id,
        artifact_id=ref.artifact_id,
        artifact_revision_id=row[0],
        revision=ref.revision,
        sha256=row[1],
        byte_length=row[2],
    )


async def require_engineering_graph_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    reference: ArtifactRevisionRef,
    originals: tuple[ArtifactRevisionRef, ...],
    *,
    recipe: str,
) -> None:
    output = await exact_artifact(session, scope, reference)
    require_acceptance(output.derivation_id == uuid5(reference.artifact_id, "derivation-v1"))
    native = await session.get(BrainDerivation, (scope.company_id, output.derivation_id))
    require_acceptance(native is not None and native.recorded_at == output.recorded_at)
    evidence = tuple(
        (
            await session.scalars(
                select(BrainDerivationEvidence.evidence_id)
                .where(
                    BrainDerivationEvidence.company_id == scope.company_id,
                    BrainDerivationEvidence.derivation_id == output.derivation_id,
                )
                .limit(1)
            )
        ).all()
    )
    require_acceptance(not evidence)
    rows: list[BrainArtifactRevision] = []
    sources: dict[UUID, SourceRevisionRef] = {}
    for ref in originals:
        row = await exact_artifact(session, scope, ref)
        rows.append(row)
        for key in await artifact_roots(session, scope, row):
            refs, _, _ = await contributors(session, scope, key)
            sources.update((item.source_revision_id, item) for item in refs)
    _, resources = await reference_sources(session, scope, originals)
    roots: tuple[SourceRevisionRef, ...] = tuple(sources[key] for key in sorted(sources))
    derivation = DerivationRecord(
        company_id=scope.company_id,
        derivation_id=uuid5(reference.artifact_id, "derivation-v1"),
        artifact=reference,
        kind="context",
        recipe_version=recipe,
        contributors=roots,
        evidence=(),
        recorded_at=output.recorded_at,
    )
    await require_replay_manifest(session, reference, derivation, tuple(rows), resources)


async def read_engineering_prerequisite_locked(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    *,
    plan: PlanRevision,
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
    credential: AuthenticatedWorkerIdentity,
    source: RegisteredBuilderSource,
    proof: EngineeringProofStorage,
    summary_policy: SourcePolicy,
) -> EngineeringPrerequisiteFacts:
    # This >50-line boundary retains exact native selectors, complete READ and receipt chronology.
    admission = catalog.cycle_admission
    require_acceptance(
        admission is not None
        and scope.task_id == work.task_id
        and scope.task_trace_id == work.trace_id
        and scope.actor_id == work.actor_id
    )
    assert admission is not None
    await require_strategy_application_role(session)
    require_credential(credential, identity, scope, await db_now(session))
    current = await require_cycle_deliverable_partition_locked(
        session, control, work, identity, admission=admission, registry=catalog.models
    )
    require_acceptance(current == plan)
    await require_brain_scope(session, control, scope, identity)
    author, _, charter = await current_work(
        session,
        control,
        plan.payload,
        plan.plan_revision_id,
        admission.slots[2].child.binding.task_id,
    )
    verifier, _, _ = await current_work(
        session,
        control,
        plan.payload,
        plan.plan_revision_id,
        admission.slots[3].child.binding.task_id,
    )
    require_acceptance(
        author.actor_id != verifier.actor_id
        and charter.verifier_id == verifier.actor_id
        and all(row.state not in {"blocked", "outcome_unknown"} for row in (author, verifier))
    )
    first_id, second_id = (
        await unique_issued_action(session, author),
        await unique_issued_action(session, verifier),
    )
    first, first_receipt, first_facts = await _issued(session, author, first_id)
    second, second_receipt, second_facts = await _issued(session, verifier, second_id)
    require_acceptance(
        first.protected_patch is not None
        and first.protected_patch == second.protected_patch
        and first.job.source == second.job.source
        and first.policy_sha256 == second.policy_sha256
        and first.runtime_inputs == second.runtime_inputs
    )
    assert first.protected_patch is not None
    acceptances = tuple(
        (
            await session.scalars(
                select(ManagementWorkAcceptance)
                .where(
                    ManagementWorkAcceptance.company_id == work.company_id,
                    ManagementWorkAcceptance.author_task_id == author.task_id,
                    ManagementWorkAcceptance.author_run_id == author.run_id,
                )
                .limit(2)
            )
        ).all()
    )
    require_acceptance(len(acceptances) == 1)
    accepted = acceptance_record(acceptances[0])
    target = accepted.target
    require_acceptance(
        accepted.verdict == "pass"
        and len(accepted.proofs) == 1
        and target.author == admission.slots[2].child.binding
        and target.verifier == admission.slots[3].child.binding
        and target.criterion_ids == ENGINEERING_CRITERIA
        and target.check_recipe == ENGINEERING_RECIPE
    )
    outputs = (await _reference(session, first_receipt), await _reference(session, second_receipt))
    check = accepted.proofs[0].result_artifact
    refs = (*outputs, check, first.protected_patch, source.metadata)
    require_acceptance(
        len({ref.artifact_revision_id for ref in refs}) == 5
        and all(ref.byte_length <= 262144 for ref in outputs)
        and check.byte_length <= 16384
        and source.metadata.byte_length <= 16384
        and target.artifacts == (outputs[0],)
        and target.action_id == first_id
        and accepted.proofs[0].recipe == ENGINEERING_RECIPE
    )
    for ref in refs:
        await artifacts.revalidate_artifact_reference(
            session, control, scope, identity, ref, await db_now(session)
        )
    await freshness.revalidate_references(session, scope, refs, await db_now(session))
    require_acceptance(
        await current_accepted_work(session, control, work, author, identity, artifacts, freshness)
        == accepted
    )
    metadata = await actual_engineering_metadata(session, target, second_id)
    require_acceptance(
        (
            metadata.author_spec,
            metadata.verifier_spec,
            metadata.author_receipt,
            metadata.verifier_receipt,
            metadata.author_output,
            metadata.verifier_output,
        )
        == (first, second, first_receipt, second_receipt, *outputs)
    )
    for spec, ref, facts in zip((first, second), outputs, (first_facts, second_facts), strict=True):
        row = await exact_artifact(session, scope, ref)
        require_acceptance(
            spec.output_resource is not None
            and tuple(
                named.resource
                for named in catalog.resources
                if named.symbol == spec.job.resource_symbol
            )
            == (spec.output_resource,)
            and row.resource_id == spec.output_resource.resource_id
            and (row.media_type, row.storage_symbol, row.data_classification)
            == (
                "application/json",
                proof.blobs.storage_symbol,
                summary_policy.data_classification,
            )
            and ref.artifact_id == uuid5(spec.job.action_id, "native-builder-protected-result-v1")
            and ref.artifact_revision_id == uuid5(ref.artifact_id, "revision-v1")
            and ref.revision == "native-builder-v1"
            and facts.created_at <= row.recorded_at <= facts.receipt.recorded_at
        )
        await require_engineering_graph_locked(
            session,
            scope,
            ref,
            (source.metadata, first.protected_patch),
            recipe="native-builder-result-v1",
        )
    row = await exact_artifact(session, scope, check)
    require_acceptance(
        row.resource_id == proof.target.resource_id
        and (row.media_type, row.storage_symbol, row.data_classification)
        == ("application/json", proof.blobs.storage_symbol, proof.policy.data_classification)
        and max(first_receipt.recorded_at, second_receipt.recorded_at)
        <= row.recorded_at
        <= accepted.recorded_at
        <= await db_now(session)
    )
    await require_engineering_graph_locked(
        session, scope, check, (*outputs, first.protected_patch), recipe=ENGINEERING_RECIPE
    )
    require_credential(credential, identity, scope, await db_now(session))
    return EngineeringPrerequisiteFacts(
        plan, accepted, metadata, check, (first_facts, second_facts), (author.fence, verifier.fence)
    )
