"""Atomic immutable invoice provenance and once-only historical budget reconciliation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.execution.billing_contracts import (
    BillingEvidenceRecord,
    BillingLookupRequest,
    BillingObservation,
    observation_digest,
)
from nexus.execution.billing_models import BillingEvidence
from nexus.execution.billing_support import evidence_record
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import lease_scope
from nexus.harness.journal_budget import reconcile_cost
from nexus.harness.journal_models import CostHold


async def record_bill(
    session: AsyncSession,
    work: ExecutionWork,
    hold: CostHold,
    request: BillingLookupRequest,
    observation: BillingObservation,
    now: datetime,
) -> BillingEvidenceRecord:
    """All changes commit with the owner's fresh control/fence; known effect remains untouched."""
    existing = await session.get(BillingEvidence, (work.company_id, observation.action_id))
    if existing is not None:
        known = evidence_record(existing)
        if (
            observation_digest(observation) != known.observation_hash
            or hold.state != "reconciled"
            or hold.actual_usd != known.observation.actual_usd
        ):
            raise ExecutionDeniedError("Conflicting billing proof/amount or ledger result denied")
        return known
    if hold.state not in {"held", "unknown"} or hold.actual_usd is not None:
        raise ExecutionDeniedError(
            "Billing reservation was resolved without this observed evidence"
        )
    row = evidence_row(work, request, observation, now)
    session.add(row)
    try:
        await session.flush()
        await reconcile_cost(
            session,
            lease_scope(request.lease.execution),
            observation.action_id,
            observation.actual_usd,
        )
        await session.flush()
    except (IntegrityError, ValueError) as exc:
        raise ExecutionDeniedError("Observed billing identity or amount conflicts") from exc
    return evidence_record(row)


def evidence_row(
    work: ExecutionWork,
    request: BillingLookupRequest,
    observation: BillingObservation,
    now: datetime,
) -> BillingEvidence:
    """Keep first evidence/source-check dates and owner audit identity immutable on replay."""
    scope = request.lease.control_scope
    return BillingEvidence(
        company_id=work.company_id,
        action_id=observation.action_id,
        evidence_id=observation.evidence_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        actor_id=work.actor_id,
        workspace_id=work.workspace_id,
        run_id=work.run_id,
        receipt_id=observation.receipt_id,
        receipt_hash=observation.receipt_hash,
        proposal_hash=observation.proposal_hash,
        external_id=observation.external_id,
        price_version=observation.price_version,
        currency=observation.currency,
        provider=observation.provider,
        source_observation_id=observation.source_observation_id,
        provider_reference=observation.provider_reference,
        invoice_reference=observation.invoice_reference,
        actual_usd=observation.actual_usd,
        proof_json=observation.proof.model_dump_json(),
        proof_sha256=observation.proof.sha256,
        observation_json=observation.model_dump_json(),
        observation_hash=observation_digest(observation),
        observed_at=observation.observed_at,
        source_checked_at=observation.source_checked_at,
        owner_id=scope.principal_id,
        operation_id=scope.operation_id,
        operation_trace_id=scope.trace_id,
        lease_fence=work.fence,
        recorded_at=now,
    )
