"""Exact historical receipt/action/price bindings and immutable billing evidence records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.billing_contracts import (
    BillingEvidenceRecord,
    BillingLookupRequest,
    BillingObservation,
    OwnerBillingLease,
    observation_digest,
    receipt_digest,
)
from nexus.execution.billing_models import BillingEvidence
from nexus.execution.effect_support import effect_row, require_receipt_binding
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction


async def billing_request(
    session: AsyncSession, work: ExecutionWork, owned: OwnerBillingLease
) -> tuple[BillingLookupRequest, CostHold]:
    """Rebind the same known receipt bytes and original price, never current replacement prices."""
    effect, action, hold, receipt = await known_billing(session, work, owned.action_id)
    assert effect.receipt_json is not None
    digest = receipt_digest(effect.receipt_json)
    if (digest, receipt.receipt_id) != (owned.receipt_hash, owned.receipt_id):
        raise ExecutionDeniedError("Known billing receipt differs from its immutable lease target")
    return (
        BillingLookupRequest(
            company_id=work.company_id,
            lease=owned,
            proposal=ActionProposal.model_validate_json(action.proposal_json),
            receipt=receipt,
            receipt_hash=digest,
        ),
        hold,
    )


async def known_billing(
    session: AsyncSession, work: ExecutionWork, action_id: UUID
) -> tuple[EffectIntent, JournalAction, CostHold, ActionReceipt]:
    """Require registered issued known outcome and its matching historical reservation."""
    effect = await effect_row(session, work, action_id)
    action = await session.get(JournalAction, action_id)
    hold = await session.get(CostHold, action_id)
    if (
        effect.state not in {"succeeded", "failed"}
        or effect.receipt_json is None
        or action is None
        or hold is None
        or (action.company_id, action.task_id, action.trace_id, action.proposal_hash)
        != (work.company_id, work.task_id, work.trace_id, effect.proposal_hash)
        or (hold.company_id, hold.task_id) != (work.company_id, work.task_id)
    ):
        raise ExecutionDeniedError("Billing requires this run's original known receipt and hold")
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    receipt = ActionReceipt.model_validate_json(effect.receipt_json)
    require_receipt_binding(effect, receipt)
    if action_hash(proposal) != effect.proposal_hash or proposal.actor_id != work.actor_id:
        raise ExecutionDeniedError("Historical billing action provenance disagrees")
    return effect, action, hold, receipt


def require_observation(request: BillingLookupRequest, observation: BillingObservation) -> None:
    """Observation is trusted composition, but its binding must still be exact and scoped."""
    receipt, proposal, lease = request.receipt, request.proposal, request.lease
    if (
        observation.company_id,
        observation.action_id,
        observation.task_id,
        observation.trace_id,
        observation.run_id,
        observation.receipt_id,
        observation.receipt_hash,
        observation.proposal_hash,
        observation.external_id,
        observation.price_version,
    ) != (
        request.company_id,
        receipt.action_id,
        receipt.task_id,
        receipt.trace_id,
        lease.execution.run_id,
        receipt.receipt_id,
        request.receipt_hash,
        receipt.proposal_hash,
        receipt.external_id,
        proposal.price_version,
    ):
        raise ExecutionDeniedError(
            "Observed invoice does not bind the original action/receipt/price"
        )
    if lease.control_scope.principal_id not in observation.proof.allowed_principals:
        raise ExecutionDeniedError("Observed invoice proof does not grant the current owner access")


def evidence_record(row: BillingEvidence) -> BillingEvidenceRecord:
    """Revalidate protected persisted content; no synthesized amount or new proof is introduced."""
    observation = BillingObservation.model_validate_json(row.observation_json)
    if observation_digest(observation) != row.observation_hash or (
        observation.company_id,
        observation.action_id,
        observation.receipt_hash,
        observation.price_version,
        observation.actual_usd,
        observation.proof.model_dump_json(),
    ) != (
        row.company_id,
        row.action_id,
        row.receipt_hash,
        row.price_version,
        row.actual_usd,
        row.proof_json,
    ):
        raise ExecutionDeniedError("Protected persisted billing evidence binding is inconsistent")
    return BillingEvidenceRecord(
        company_id=row.company_id,
        observation=observation,
        observation_hash=row.observation_hash,
        owner_id=row.owner_id,
        operation_id=row.operation_id,
        operation_trace_id=row.operation_trace_id,
        lease_fence=row.lease_fence,
        recorded_at=row.recorded_at,
    )
