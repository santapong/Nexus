"""Persisted observed billing is a native cost fact; its proof retains independent source ACL."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.execution.billing_contracts import BillingObservation, receipt_digest
from nexus.execution.billing_models import BillingEvidence
from nexus.execution.billing_support import evidence_record
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold


async def billing_proofs(
    session: AsyncSession,
    work: ExecutionWork,
) -> tuple[ArtifactRevisionRef, ...]:
    rows = (
        await session.scalars(
            select(BillingEvidence)
            .where(
                BillingEvidence.company_id == work.company_id,
                BillingEvidence.task_id == work.task_id,
            )
            .order_by(BillingEvidence.action_id)
        )
    ).all()
    require_acceptance(len(rows) <= 1000)
    result = []
    for row in rows:
        observation = evidence_record(row).observation
        await exact_invoice(session, work, row, observation)
        proof = observation.proof
        artifact = await session.scalar(
            select(BrainArtifactRevision).where(
                BrainArtifactRevision.company_id == work.company_id,
                BrainArtifactRevision.artifact_id == proof.artifact_id,
                BrainArtifactRevision.revision == proof.revision,
            )
        )
        require_acceptance(artifact is not None and artifact.sha256 == proof.sha256)
        assert artifact is not None
        result.append(
            ArtifactRevisionRef(
                company_id=artifact.company_id,
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.artifact_revision_id,
                revision=artifact.revision,
                sha256=artifact.sha256,
                byte_length=artifact.byte_length,
            )
        )
    return tuple(result)


async def exact_invoice(
    session: AsyncSession,
    work: ExecutionWork,
    row: BillingEvidence,
    observation: BillingObservation,
) -> None:
    effect = await session.get(EffectIntent, (work.company_id, row.action_id))
    cost = await session.get(CostHold, row.action_id)
    require_acceptance(effect is not None and effect.receipt_json is not None and cost is not None)
    assert effect is not None and effect.receipt_json is not None and cost is not None
    receipt = ActionReceipt.model_validate_json(effect.receipt_json)
    require_acceptance(
        (row.task_id, row.trace_id, row.actor_id, row.workspace_id, row.run_id)
        == (work.task_id, work.trace_id, work.actor_id, work.workspace_id, work.run_id)
        and (observation.task_id, observation.trace_id, observation.run_id)
        == (work.task_id, work.trace_id, work.run_id)
        and (effect.task_id, effect.trace_id, effect.run_id)
        == (work.task_id, work.trace_id, work.run_id)
        and (receipt.company_id, receipt.action_id, receipt.task_id, receipt.trace_id)
        == (work.company_id, row.action_id, work.task_id, work.trace_id)
        and effect.state == receipt.outcome
        and effect.state in {"succeeded", "failed"}
        and receipt.receipt_id == observation.receipt_id == row.receipt_id
        and row.observed_at == observation.observed_at
        and row.source_checked_at == observation.source_checked_at
        and receipt_digest(effect.receipt_json) == observation.receipt_hash == row.receipt_hash
        and effect.proposal_hash == observation.proposal_hash == row.proposal_hash
        and cost.company_id == work.company_id
        and cost.task_id == work.task_id
        and cost.state == "reconciled"
        and cost.actual_usd == observation.actual_usd
        and row.proof_sha256 == observation.proof.sha256
        and observation.proof.company_id == work.company_id
    )
