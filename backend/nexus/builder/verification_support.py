"""Independent candidates require actual current native receipts and full protected bytes."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.plan_models import ManagementVerificationBinding
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import JournalAction


async def require_verifier_binding(
    session: AsyncSession,
    lease: ExecutionLease,
    author: BuilderRunResult,
    verifier: BuilderRunResult,
) -> None:
    current = await ManagementPlanStore.current_binding(session, lease.company_id, lease.task_id)
    first = await ManagementPlanStore.current_binding(
        session, lease.company_id, author.spec.job.task_id
    )
    if (
        current is None
        or first is None
        or current.plan.plan_revision_id != first.plan.plan_revision_id
    ):
        raise ValueError("Builder author/verifier current plan binding differs")
    edge = await session.scalar(
        select(ManagementVerificationBinding).where(
            ManagementVerificationBinding.company_id == lease.company_id,
            ManagementVerificationBinding.plan_revision_id == current.plan.plan_revision_id,
            ManagementVerificationBinding.author_task_id == author.spec.job.task_id,
            ManagementVerificationBinding.verifier_task_id == lease.task_id,
        )
    )
    if (
        edge is None
        or author.spec.job.actor_id == verifier.spec.job.actor_id
        or (
            verifier.spec.job.company_id,
            verifier.spec.job.task_id,
            verifier.spec.job.trace_id,
            verifier.spec.job.actor_id,
            verifier.spec.job.run_id,
            verifier.spec.job.workspace_id,
        )
        != (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.actor_id,
            lease.run_id,
            lease.workspace_id,
        )
    ):
        raise ValueError("Builder distinct native verifier binding is unavailable")


async def actual_result_reference(
    session: AsyncSession, result: BuilderRunResult
) -> ArtifactRevisionRef:
    job = result.spec.job
    intent = await session.get(EffectIntent, (job.company_id, job.action_id))
    action = await session.get(JournalAction, job.action_id)
    if (
        intent is None
        or action is None
        or intent.state != "succeeded"
        or intent.receipt_json is None
        or (
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.intent_fence,
            intent.proposal_hash,
        )
        != (job.task_id, job.trace_id, job.run_id, result.intent_fence, result.proposal_sha256)
        or (
            action.proposal_hash != result.proposal_sha256
            or ActionProposal.model_validate_json(action.proposal_json).parameters
            != result.spec.model_dump(mode="json")
        )
    ):
        raise ValueError("Builder result needs its actual exact succeeded native receipt")
    receipt = ActionReceipt.model_validate_json(intent.receipt_json)
    if receipt.outcome != "succeeded" or len(receipt.artifacts) != 1:
        raise ValueError("Builder actual output receipt is unavailable")
    ref = receipt.artifacts[0]
    native = await session.scalar(
        select(BrainArtifactRevision).where(
            BrainArtifactRevision.company_id == job.company_id,
            BrainArtifactRevision.artifact_id == ref.artifact_id,
            BrainArtifactRevision.revision == ref.revision,
            BrainArtifactRevision.sha256 == ref.sha256,
        )
    )
    if native is None or native.byte_length > 262144:
        raise ValueError("File-only builder history cannot supply protected verification evidence")
    return ArtifactRevisionRef(
        company_id=native.company_id,
        artifact_id=native.artifact_id,
        artifact_revision_id=native.artifact_revision_id,
        revision=native.revision,
        sha256=native.sha256,
        byte_length=native.byte_length,
    )


async def actual_summary(
    guard: BuilderSourceGuard, result: BuilderRunResult, reference: ArtifactRevisionRef
) -> None:
    body = bytearray()
    while len(body) < reference.byte_length:
        value = await guard.artifacts.bounded_artifact(
            guard.scope(),
            guard.identity,
            reference.artifact_revision_id,
            start_byte=len(body),
            max_bytes=16384,
            include_history=False,
        )
        if (
            value.artifact != reference
            or value.source_state != "current"
            or value.span.start_byte != len(body)
        ):
            raise ValueError("Builder protected result changed during materialization")
        body.extend(value.text.encode())
    if hashlib.sha256(body).hexdigest() != reference.sha256 or len(body) != reference.byte_length:
        raise ValueError("Builder actual protected summary bytes differ")
    value = json.loads(body)
    if (
        value.get("result_sha256"),
        value.get("spec"),
        value.get("proposal_sha256"),
        value.get("intent_fence"),
    ) != (
        BuilderResultStore.digest(result),
        result.spec.model_dump(mode="json"),
        result.proposal_sha256,
        result.intent_fence,
    ):
        raise ValueError("Builder decoded result differs from actual protected native evidence")
