"""Resolve one actual engineering author/verifier issued pair from the approved native edge."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_contracts import ENGINEERING_CRITERIA, ENGINEERING_RECIPE
from nexus.builder.engineering_metadata import EngineeringMetadata, actual_engineering_metadata
from nexus.builder.engineering_targets import engineering_work_pair
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import actual_receipt, receipt_artifacts
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction


@dataclass(frozen=True)
class EngineeringPairSelection:
    """Resolved records supply selectors; construction gives no recording permission."""

    target: VerificationSpec
    metadata: EngineeringMetadata
    author_action_id: UUID
    verifier_action_id: UUID


async def unique_author_action(session: AsyncSession, author: ExecutionWork) -> UUID:
    """Count all succeeded builder identities first; no invalid candidate can be filtered away."""
    rows = (
        await session.execute(
            select(EffectIntent, JournalAction)
            .outerjoin(JournalAction, JournalAction.id == EffectIntent.action_id)
            .where(
                EffectIntent.company_id == author.company_id,
                EffectIntent.task_id == author.task_id,
                EffectIntent.run_id == author.run_id,
                EffectIntent.state == "succeeded",
            )
            .order_by(EffectIntent.action_id)
            .limit(3)
        )
    ).all()
    require_acceptance(len(rows) == 1)
    for _effect, action in rows:
        require_acceptance(action is not None)
        assert action is not None
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        require_acceptance(
            proposal.tool == "company.builder.run.v1" and action.company_id == author.company_id
        )
    selected = rows[0][0]
    assert isinstance(selected, EffectIntent)
    return selected.action_id


async def resolve_pair(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    *,
    verifier_action_id: UUID,
) -> EngineeringPairSelection:
    """Current approved edge and exact native succeeded receipts establish one closed pair."""
    author, verifier = await engineering_work_pair(session, control, lease)
    author_action_id = await unique_author_action(session, author)
    await actual_receipt(session, verifier, verifier_action_id)
    first = await ManagementPlanStore.current_binding(session, lease.company_id, author.task_id)
    second = await ManagementPlanStore.current_binding(session, lease.company_id, verifier.task_id)
    require_acceptance(first is not None and second is not None)
    assert first is not None and second is not None
    receipt = await actual_receipt(session, author, author_action_id)
    target = VerificationSpec(
        company_id=lease.company_id,
        author=first.child.binding,
        verifier=second.child.binding,
        action_id=author_action_id,
        proposal_sha256=receipt.proposal_hash,
        receipt_id=receipt.receipt_id,
        receipt_sha256=canonical_sha256(receipt),
        work_snapshot_sha256=author.registration_hash,
        criterion_ids=ENGINEERING_CRITERIA,
        artifacts=await receipt_artifacts(session, receipt),
        check_recipe=ENGINEERING_RECIPE,
    )
    metadata = await actual_engineering_metadata(session, target, verifier_action_id)
    first_spec, second_spec = metadata.author_spec, metadata.verifier_spec
    require_acceptance(
        first_spec.job.source == second_spec.job.source
        and first_spec.protected_patch == second_spec.protected_patch
        and first_spec.policy_sha256 == second_spec.policy_sha256
        and first_spec.runtime_inputs == second_spec.runtime_inputs
    )
    return EngineeringPairSelection(target, metadata, author_action_id, verifier_action_id)
