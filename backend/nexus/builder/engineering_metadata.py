"""Actual immutable engineering receipt/spec/output/registration lookup under caller transaction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import actual_receipt, receipt_artifacts
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.execution.runtime_contracts import ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction


@dataclass(frozen=True)
class EngineeringMetadata:
    procedure_id: UUID
    author_spec: BuilderExecutionSpec
    verifier_spec: BuilderExecutionSpec
    author_receipt: ActionReceipt
    verifier_receipt: ActionReceipt
    author_registration: ExecutionRegistration
    verifier_registration: ExecutionRegistration
    author_output: ArtifactRevisionRef
    verifier_output: ArtifactRevisionRef


async def actual_engineering_metadata(
    session: AsyncSession,
    target: VerificationSpec,
    verifier_action_id: UUID,
) -> EngineeringMetadata:
    first = await session.get(ExecutionWork, (target.company_id, target.author.task_id))
    second = await session.get(ExecutionWork, (target.company_id, target.verifier.task_id))
    require_acceptance(first is not None and second is not None)
    assert first is not None and second is not None
    author = await ManagementPlanStore.current_binding(session, target.company_id, first.task_id)
    verifier = await ManagementPlanStore.current_binding(session, target.company_id, second.task_id)
    require_acceptance(
        author is not None
        and verifier is not None
        and author.procedure_id == verifier.procedure_id
        and author.plan == verifier.plan
    )
    assert author is not None
    receipts = (
        await actual_receipt(session, first, target.action_id),
        await actual_receipt(session, second, verifier_action_id),
    )
    specs: list[BuilderExecutionSpec] = []
    outputs: list[ArtifactRevisionRef] = []
    for receipt, work in zip(receipts, (first, second), strict=True):
        spec, output = await _spec_output(session, receipt, work)
        specs.append(spec)
        outputs.append(output)
    require_acceptance(
        canonical_sha256(receipts[0]) == target.receipt_sha256
        and receipts[0].receipt_id == target.receipt_id
        and (outputs[0],) == target.artifacts
    )
    return EngineeringMetadata(
        author.procedure_id,
        specs[0],
        specs[1],
        receipts[0],
        receipts[1],
        snapshot(first).registration,
        snapshot(second).registration,
        outputs[0],
        outputs[1],
    )


async def _spec_output(
    session: AsyncSession,
    receipt: ActionReceipt,
    work: ExecutionWork,
) -> tuple[BuilderExecutionSpec, ArtifactRevisionRef]:
    action = await session.get(JournalAction, receipt.action_id)
    require_acceptance(action is not None)
    assert action is not None
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    require_acceptance(
        proposal.tool == "company.builder.run.v1"
        and proposal.tool_version == "v1"
        and action.proposal_hash == receipt.proposal_hash == action_hash(proposal)
    )
    spec = BuilderExecutionSpec.model_validate_json(json.dumps(proposal.parameters))
    require_acceptance(
        (
            spec.job.company_id,
            spec.job.task_id,
            spec.job.trace_id,
            spec.job.action_id,
            spec.job.actor_id,
        )
        == (
            proposal.company_id,
            proposal.task_id,
            proposal.trace_id,
            proposal.action_id,
            proposal.actor_id,
        )
    )
    require_acceptance(
        (spec.job.run_id, spec.job.workspace_id, spec.job.actor_id)
        == (work.run_id, work.workspace_id, work.actor_id)
    )
    refs = await receipt_artifacts(session, receipt)
    require_acceptance(len(refs) == 1)
    return spec, refs[0]
