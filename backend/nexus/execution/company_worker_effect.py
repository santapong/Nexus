"""One uncheckpointed offline invocation/known-output reconciliation sequence.

The complete sequence stays inside its caller's single DBOS I/O step; helpers
below are ordinary functions and never checkpoint a one-time permit separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid5

from pydantic_ai import Agent

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt, VerificationResult
from nexus.execution.company_worker_contracts import OfflineOutput, WorkerResult
from nexus.execution.company_worker_support import (
    DraftParameters,
    OfflineArtifacts,
    OfflineWorkerServices,
    database_clock,
    generate_draft,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import AttemptKind, EffectRecord, ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import lease_scope


@dataclass(frozen=True)
class EffectContext:
    """Trusted process-local services, never passed to or returned from a DBOS checkpoint."""

    services: OfflineWorkerServices
    agent: Agent[None, str]
    execution: ExecutionStore
    effects: EffectStore
    lease: ExecutionLease
    identity: VerifiedIdentity
    command: SegmentCommand
    action: ActionProposal
    owner_id: UUID


async def run_effect(context: EffectContext) -> WorkerResult:
    """Resolve an issued result or invoke once, then preserve an inconclusive candidate."""
    artifacts = OfflineArtifacts(context.services.artifact_root)
    record = (
        await recover_output(context, artifacts)
        if context.lease.mode == "reconcile"
        else await invoke_once(context, artifacts)
    )
    if record.receipt is None or record.receipt.outcome != "succeeded":
        return result(context.command, "outcome_unknown", record.receipt)
    current = await context.execution.get(lease_scope(context.lease), context.identity)
    candidate = VerificationResult(
        company_id=context.command.company_id,
        verification_id=uuid5(context.command.action_id, "offline-verification-v1"),
        action_id=context.command.action_id,
        verifier_id=uuid5(context.command.actor_id, "offline-verifier-v1"),
        verdict="inconclusive",
        criterion_ids=current.registration.work.acceptance,
        limitations=("Offline output only; independent company acceptance has not run",),
    )
    await context.effects.record_verification_candidate(context.lease, context.identity, candidate)
    return result(context.command, "verifying", record.receipt)


async def recover_output(context: EffectContext, artifacts: OfflineArtifacts) -> EffectRecord:
    """Only preserved exact output can resolve an issued unknown effect; never call again."""
    record = await context.effects.get(context.lease, context.identity, context.command.action_id)
    output = await artifacts.load(context.command)
    if record.receipt is None and output is not None:
        output.require_binding(
            context.command.company_id,
            context.command.task_id,
            context.command.trace_id,
            context.command.action_id,
            record.proposal_hash,
        )
        receipt = await make_receipt(artifacts, context.command, output, context.owner_id)
        return await context.effects.reconcile(
            context.lease, context.identity, receipt, actual_usd=Decimal(0)
        )
    return record


async def invoke_once(context: EffectContext, artifacts: OfflineArtifacts) -> EffectRecord:
    """Begin, invoke, save output and record receipt inside one uncheckpointed adapter call."""
    kind: AttemptKind = (
        "model_requests" if context.action.tool == "fake.internal.draft.v1" else "tool_attempts"
    )
    start = await context.effects.begin(
        context.lease,
        context.identity,
        context.command.action_id,
        resources=context.services.resources,
        kind=kind,
    )
    if not start.permit_external_call:
        return start.record
    await context.services.observe("intent_committed", context.command)
    output = await produce_output(context, start.record)
    await artifacts.save(context.command, output)
    await context.services.observe("output_saved", context.command)
    receipt = await make_receipt(artifacts, context.command, output, context.owner_id)
    record = await context.effects.record_receipt(
        context.lease, context.identity, receipt, actual_usd=Decimal(0)
    )
    await context.services.observe("receipt_recorded", context.command)
    return record


async def produce_output(context: EffectContext, record: EffectRecord) -> OfflineOutput:
    """Count the model/tool attempts before their actual invocation or artifact write."""
    draft = context.action.tool == "fake.internal.draft.v1"
    text = "Synthetic read-only source; no real StockFlow evidence."
    if draft:
        text = await generate_draft(
            context.agent, DraftParameters.model_validate(context.action.parameters)
        )
        await context.services.observe("model_called", context.command)
        await context.execution.reserve_attempt(
            context.lease,
            context.identity,
            "tool_attempts",
            uuid5(context.command.action_id, "offline-tool-v1"),
        )
    return OfflineOutput(
        company_id=context.command.company_id,
        task_id=context.command.task_id,
        trace_id=context.command.trace_id,
        action_id=context.command.action_id,
        proposal_hash=record.proposal_hash,
        tool=cast(Literal["fake.internal.read.v1", "fake.internal.draft.v1"], context.action.tool),
        tool_version="v1",
        output=text,
        model_requests=1 if draft else 0,
        tool_attempts=1,
        recorded_at=await database_clock(context.services.factory),
    )


async def make_receipt(
    artifacts: OfflineArtifacts, command: SegmentCommand, output: OfflineOutput, owner: UUID
) -> ActionReceipt:
    """Bind the receipt to actual preserved bytes and the original committed effect."""
    return ActionReceipt(
        company_id=command.company_id,
        receipt_id=uuid5(command.action_id, "offline-receipt-v1"),
        action_id=command.action_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        proposal_hash=output.proposal_hash,
        outcome="succeeded",
        recorded_at=output.recorded_at,
        artifacts=(await artifacts.reference(command, owner),),
    )


def result(command: SegmentCommand, status: str, receipt: ActionReceipt | None) -> WorkerResult:
    """A workflow return cannot manufacture company completion."""
    return WorkerResult.model_validate(
        {
            "company_id": command.company_id,
            "task_id": command.task_id,
            "action_id": command.action_id,
            "segment_id": command.segment_id,
            "status": status,
            "receipt_id": receipt.receipt_id if receipt else None,
            "limitations": ("Offline adapter; business completion is not established",),
        }
    )
