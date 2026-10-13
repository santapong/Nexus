"""Resolve exact current native approved verifier/author/receipt targets under CompanyControl."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance as denied
from nexus.company.management.acceptance_targets import current_governance, current_work
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_RECIPE
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import execution_row, lease_scope, require_lease, snapshot
from nexus.harness.journal_models import CompanyControl


def acceptance_scope(lease: ExecutionLease, action_id: UUID) -> BrainReadScope:
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=lease.actor_id,
        operation_id=uuid5(lease.segment_id, f"acceptance:{action_id}"),
        trace_id=lease.trace_id,
        task_id=lease.task_id,
        task_trace_id=lease.trace_id,
        actor_id=lease.actor_id,
    )


def plan_query(
    lease: ExecutionLease,
) -> Select[tuple[ManagementPlanRevision, ManagementVerificationBinding, ManagementPlanHead]]:
    return (
        select(ManagementPlanRevision, ManagementVerificationBinding, ManagementPlanHead)
        .join(
            ManagementPlanHead,
            (ManagementPlanHead.company_id == ManagementPlanRevision.company_id)
            & (ManagementPlanHead.current_revision_id == ManagementPlanRevision.plan_revision_id),
        )
        .join(
            ManagementVerificationBinding,
            (ManagementVerificationBinding.company_id == ManagementPlanRevision.company_id)
            & (
                ManagementVerificationBinding.plan_revision_id
                == ManagementPlanRevision.plan_revision_id
            ),
        )
        .where(
            ManagementPlanRevision.company_id == lease.company_id,
            ManagementPlanHead.state == "approved",
            ManagementVerificationBinding.verifier_task_id == lease.task_id,
        )
    )


async def native_plan(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
) -> tuple[ManagementPlanRevision, PlanPayload, ManagementVerificationBinding]:
    denied(
        not bool(
            await session.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
        )
    )
    selected = await ManagementPlanStore.current_binding(session, lease.company_id, lease.task_id)
    denied(selected is not None)
    assert selected is not None
    rows = (
        await session.execute(
            plan_query(lease).where(
                ManagementPlanRevision.plan_revision_id == selected.plan.plan_revision_id
            )
        )
    ).all()
    denied(len(rows) == 1)
    revision, binding, head = rows[0]
    payload = stored_plan(revision, lease.company_id)
    decision = await session.get(ManagementOwnerDecision, (lease.company_id, head.decision_id))
    denied(
        decision is not None
        and decision.kind == "approve"
        and decision.owner_id == control.owner_id
        and decision.plan_revision_id == revision.plan_revision_id
        and decision.payload_sha256 == revision.sha256
    )
    denied(
        head.procedure_id == payload.procedure.procedure_id
        and binding.check_recipe == REPORT_CHECK_RECIPE
        and any(
            (row.author_task_id, row.verifier_task_id, row.check_recipe)
            == (binding.author_task_id, binding.verifier_task_id, binding.check_recipe)
            for row in payload.verification
        )
    )
    return revision, payload, binding


def stored_plan(revision: ManagementPlanRevision, company_id: UUID) -> PlanPayload:
    payload = PlanPayload.model_validate_json(revision.snapshot_json)
    denied(canonical_sha256(payload) == revision.sha256 and payload.company_id == company_id)
    denied(
        (
            payload.plan.plan_id,
            payload.plan.revision,
            payload.goal.goal_id,
            payload.goal.revision_id,
            payload.mandate.revision_id,
        )
        == (
            revision.plan_id,
            revision.revision,
            revision.goal_id,
            revision.goal_revision_id,
            revision.mandate_revision_id,
        )
    )
    return payload


async def actual_receipt(
    session: AsyncSession,
    author: ExecutionWork,
    action_id: UUID,
) -> ActionReceipt:
    effect = await session.get(EffectIntent, (author.company_id, action_id))
    denied(effect is not None and effect.state == "succeeded" and effect.receipt_json is not None)
    assert effect is not None and effect.receipt_json is not None
    receipt = ActionReceipt.model_validate_json(effect.receipt_json)
    denied(
        (effect.task_id, effect.trace_id, effect.run_id)
        == (author.task_id, author.trace_id, author.run_id)
    )
    denied(
        (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
        )
        == (
            author.company_id,
            action_id,
            author.task_id,
            author.trace_id,
            effect.proposal_hash,
            "succeeded",
        )
    )
    return receipt


async def receipt_artifacts(
    session: AsyncSession, receipt: ActionReceipt
) -> tuple[ArtifactRevisionRef, ...]:
    denied(0 < len(receipt.artifacts) <= 32)
    result: list[ArtifactRevisionRef] = []
    for ref in receipt.artifacts:
        row = await session.scalar(
            select(BrainArtifactRevision).where(
                BrainArtifactRevision.company_id == receipt.company_id,
                BrainArtifactRevision.artifact_id == ref.artifact_id,
                BrainArtifactRevision.revision == ref.revision,
            )
        )
        denied(
            row is not None and ref.company_id == receipt.company_id and row.sha256 == ref.sha256
        )
        assert row is not None
        result.append(
            ArtifactRevisionRef(
                company_id=row.company_id,
                artifact_id=row.artifact_id,
                artifact_revision_id=row.artifact_revision_id,
                revision=row.revision,
                sha256=row.sha256,
                byte_length=row.byte_length,
            )
        )
    return tuple(result)


async def resolve_target(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    action_id: UUID,
    now: datetime,
) -> VerificationSpec:
    verifier = await execution_row(session, lease_scope(lease))
    require_lease(verifier, lease, now, execute=True)
    revision, payload, binding = await native_plan(session, control, lease)
    await current_governance(session, control, payload)
    author, selected_author, author_charter = await current_work(
        session, control, payload, revision.plan_revision_id, binding.author_task_id
    )
    current_verifier, selected_verifier, _ = await current_work(
        session, control, payload, revision.plan_revision_id, binding.verifier_task_id
    )
    denied(
        current_verifier.task_id == verifier.task_id
        and author.actor_id != verifier.actor_id
        and author.task_id != verifier.task_id
        and author_charter.verifier_id == verifier.actor_id
        and author.state not in {"outcome_unknown", "blocked"}
    )
    receipt = await actual_receipt(session, author, action_id)
    return VerificationSpec(
        company_id=lease.company_id,
        author=selected_author.binding,
        verifier=selected_verifier.binding,
        action_id=action_id,
        proposal_sha256=receipt.proposal_hash,
        receipt_id=receipt.receipt_id,
        receipt_sha256=canonical_sha256(receipt),
        work_snapshot_sha256=author.registration_hash,
        criterion_ids=snapshot(author).registration.work.acceptance,
        artifacts=await receipt_artifacts(session, receipt),
        check_recipe=binding.check_recipe,
    )
