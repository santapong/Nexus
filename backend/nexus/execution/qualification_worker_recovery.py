"""Reconcile actual protected SDK observations without fresh provider permission or a retry."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest
from nexus.core.llm.company_pricing import quote_cost, reconcile_cost
from nexus.core.llm.qualification_contracts import QualificationRecipe, financial_bounds
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_support import effect_record
from nexus.execution.qualification_worker_context import (
    QualificationContext,
    QualificationOperation,
    revalidate_history,
)
from nexus.execution.runtime_contracts import EffectRecord
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import runtime_transaction
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CostHold
from nexus.harness.qualification_client import QualificationRunResult
from nexus.harness.qualification_evidence import IssuedQualificationEvidence


class QualificationSegmentResult(BaseModel):
    """Durable observation and resource state, never model activation or company completion."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    command: SegmentCommand
    status: Literal["observed", "failed", "outcome_unknown", "blocked"]
    receipt: ActionReceipt | None = None
    evidence: ArtifactRef | None = None
    replayed: bool = False
    resources_pending: bool = False
    lease_released: bool = False
    error_type: str | None = None
    profile_quality_evaluated: Literal[False] = False
    company_completed: Literal[False] = False


@dataclass(frozen=True, slots=True)
class QualificationHoldFacts:
    """Actual native cost-row projection for the shared protected-result read join."""

    company_id: UUID
    task_id: UUID
    action_id: UUID
    day: date
    amount_usd: Decimal
    actual_usd: Decimal | None
    state: Literal["held", "unknown", "reconciled"]


def receipt_for(found: IssuedQualificationEvidence) -> tuple[ActionReceipt, Decimal | None]:
    """Rebuild only original issued facts; current prices/health/goal cannot grant permission."""
    value, result, intent = found.evidence, found.evidence.provider_result, found.evidence.intent
    actual = (
        reconcile_cost(value.recipe.target.price, result.usage, now=intent.created_at).amount_usd
        if result.usage is not None
        else None
    )
    outcome: Literal["succeeded", "failed", "outcome_unknown"] = (
        "outcome_unknown"
        if result.billing == "unknown"
        else "succeeded"
        if result.status == "response" and not value.caller_interrupted_at_capture
        else "failed"
    )
    request = value.request
    return ActionReceipt(
        company_id=request.company_id,
        receipt_id=uuid5(request.action_id, "qualification-receipt-v1"),
        action_id=request.action_id,
        task_id=request.task_id,
        trace_id=request.trace_id,
        proposal_hash=intent.proposal_hash,
        outcome=outcome,
        recorded_at=value.checked_at,
        artifacts=(found.reference,),
    ), actual


def require_saved_result(
    recipe: QualificationRecipe,
    request: CompanyModelRequest,
    record: EffectRecord,
    found: IssuedQualificationEvidence,
    hold: QualificationHoldFacts,
) -> QualificationRunResult:
    """Exact historical SDK/native/billing facts shared by worker and current-owner reads.

    A saved response may precede a later interruption and a conservative failed
    native receipt. Preserve that failure; never upgrade it to succeeded.
    """
    value = found.evidence
    original = record.model_copy(update={"state": "intent", "receipt": None, "verification": None})
    receipt, actual = receipt_for(found)
    if record.state == "failed" and receipt.outcome == "succeeded":
        receipt = receipt.model_copy(update={"outcome": "failed"})
    quote = quote_cost(recipe.target.price, financial_bounds(recipe), now=record.created_at)
    if (
        value.recipe != recipe
        or value.request != request
        or value.intent != original
        or record.receipt != receipt
        or record.state != receipt.outcome
        or (
            found.reference.company_id,
            found.reference.artifact_id,
            found.reference.revision,
            found.reference.allowed_principals,
        )
        != (
            request.company_id,
            uuid5(request.action_id, f"qualification:{request.request_id}"),
            "model-qualification-envelope-v1",
            (request.actor_id,),
        )
        or request.price_version != quote.price_version
        or (
            hold.company_id,
            hold.task_id,
            hold.action_id,
            hold.day,
            hold.amount_usd,
            hold.actual_usd,
            hold.state,
        )
        != (
            record.company_id,
            record.task_id,
            record.action_id,
            billing_day(record.created_at),
            quote.amount_usd,
            actual,
            "unknown" if actual is None else "reconciled",
        )
    ):
        raise ValueError("Qualification protected result differs from exact native receipt/billing")
    return QualificationRunResult(
        provider_result=value.provider_result,
        evidence=found.reference,
        record=record,
        actual_usd=actual,
        caller_interrupted=value.caller_interrupted_at_capture,
    )


async def _hold(
    operation: QualificationOperation,
    context: QualificationContext,
    record: EffectRecord,
) -> QualificationHoldFacts:
    async with runtime_transaction(
        operation.services.factory,
        context.scope,
        context.credential.identity,
        allow_paused=True,
        allow_inactive=True,
        owner_read=True,
    ) as (session, control, _):
        native = await session.get(EffectIntent, (record.company_id, record.action_id))
        row = await session.get(CostHold, record.action_id)
        if (
            control.owner_id != context.credential.identity.principal_id
            or native is None
            or effect_record(native) != record
            or row is None
        ):
            raise ValueError("Qualification actual native receipt/cost row changed")
        from nexus.execution.runtime_support import db_now

        context.credential.require_time(await db_now(session))
        return QualificationHoldFacts(
            row.company_id,
            row.task_id,
            row.action_id,
            row.day,
            row.amount_usd,
            row.actual_usd,
            cast(Literal["held", "unknown", "reconciled"], row.state),
        )


async def recover_issued(
    operation: QualificationOperation, context: QualificationContext, *, end_us: int
) -> QualificationRunResult | None:
    """Missing bytes preserve unknown; only exact saved observations can settle the hold."""
    record = context.issued
    if record is None:
        raise ValueError("Qualification recovery needs actual native issuance")
    found = await operation.call(
        operation.services.evidence.find_issued(
            context.request,
            record,
            end_us=end_us,
        ),
        end_us=end_us,
    )
    if found is None:
        if record.state in {"succeeded", "failed"}:
            raise ValueError("Known qualification receipt lacks complete protected evidence")
        return None
    if found.evidence.recipe != context.recipe:
        raise ValueError("Qualification saved recipe differs from the fixed dispatched recipe")
    await operation.call(revalidate_history(operation, context), end_us=end_us)
    receipt, actual = receipt_for(found)
    if record.state not in {"succeeded", "failed"}:
        if operation.lease is None or operation.lease.mode != "reconcile":
            raise ValueError("Qualification unknown settlement needs its actual reconcile lease")
        record = await operation.call(
            operation.services.effects.reconcile(
                operation.lease,
                context.credential.identity,
                receipt,
                actual_usd=actual,
            ),
            end_us=end_us,
        )
    hold = await operation.call(_hold(operation, context, record), end_us=end_us)
    return require_saved_result(context.recipe, context.request, record, found, hold)


def segment_result(
    command: SegmentCommand,
    outcome: QualificationRunResult | None,
    *,
    replayed: bool = False,
    failure: BaseException | None = None,
    pending: bool = False,
    released: bool = False,
    issued_record: EffectRecord | None = None,
) -> QualificationSegmentResult:
    """Never turn known usage, a completed workflow or an expired prefix into qualification."""
    record: EffectRecord | None = outcome.record if outcome else issued_record
    status: Literal["observed", "failed", "outcome_unknown", "blocked"] = "blocked"
    if record is not None:
        status = (
            "observed"
            if record.state == "succeeded"
            else ("failed" if record.state == "failed" else "outcome_unknown")
        )
    if pending or failure is not None or (outcome is not None and outcome.recording_error):
        status = "outcome_unknown" if outcome is not None or record is not None else "blocked"
    return QualificationSegmentResult(
        command=command,
        status=status,
        receipt=record.receipt if record else None,
        evidence=outcome.evidence if outcome else None,
        replayed=replayed,
        resources_pending=pending,
        lease_released=released,
        error_type=type(failure).__name__ if failure else None,
    )
