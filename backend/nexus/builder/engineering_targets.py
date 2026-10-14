"""Resolve actual approved engineering targets; never reinterpret report bindings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_contracts import ENGINEERING_CRITERIA, ENGINEERING_RECIPE
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import (
    actual_receipt,
    plan_query,
    receipt_artifacts,
    stored_plan,
)
from nexus.company.management.acceptance_targets import current_governance, current_work
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_models import ManagementOwnerDecision, ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    snapshot,
)
from nexus.harness.journal_models import CompanyControl


async def engineering_plan(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
) -> tuple[PlanPayload, UUID, UUID]:
    require_acceptance(
        not bool(
            await session.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
        )
    )
    current = await ManagementPlanStore.current_binding(session, lease.company_id, lease.task_id)
    require_acceptance(current is not None)
    assert current is not None
    rows = (
        await session.execute(
            plan_query(lease).where(
                ManagementPlanRevision.plan_revision_id == current.plan.plan_revision_id
            )
        )
    ).all()
    require_acceptance(len(rows) == 1)
    revision, edge, head = rows[0]
    payload = stored_plan(revision, lease.company_id)
    decision = await session.get(ManagementOwnerDecision, (lease.company_id, head.decision_id))
    require_acceptance(
        decision is not None
        and decision.kind == "approve"
        and decision.owner_id == control.owner_id
        and decision.plan_revision_id == revision.plan_revision_id
        and decision.payload_sha256 == revision.sha256
        and head.procedure_id == payload.procedure.procedure_id
    )
    require_acceptance(
        edge.check_recipe == ENGINEERING_RECIPE
        and any(
            (item.author_task_id, item.verifier_task_id, item.check_recipe)
            == (edge.author_task_id, edge.verifier_task_id, ENGINEERING_RECIPE)
            for item in payload.verification
        )
    )
    return payload, revision.plan_revision_id, edge.author_task_id


async def engineering_work_pair(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
) -> tuple[ExecutionWork, ExecutionWork]:
    payload, revision, author_task = await engineering_plan(session, control, lease)
    await current_governance(session, control, payload)
    author, first, charter = await current_work(session, control, payload, revision, author_task)
    verifier, second, _ = await current_work(session, control, payload, revision, lease.task_id)
    require_acceptance(
        author.actor_id != verifier.actor_id
        and author.task_id != verifier.task_id
        and charter.verifier_id == verifier.actor_id
        and author.state not in {"outcome_unknown", "blocked"}
    )
    require_acceptance(
        (
            first.binding.workflow_name,
            first.binding.workflow_version,
            first.binding.model_profile,
            second.binding.workflow_name,
            second.binding.workflow_version,
            second.binding.model_profile,
        )
        == (
            "engineering.change",
            "v1",
            "engineering.native.v1",
            "engineering.verify",
            "v1",
            "verification.native.v1",
        )
    )
    for work in (author, verifier):
        registered = snapshot(work).registration
        require_acceptance(
            registered.quota.model_requests == 0
            and registered.work.acceptance == ENGINEERING_CRITERIA
        )
    return author, verifier


async def resolve_engineering_target(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    author_action_id: UUID,
) -> VerificationSpec:
    actual = await execution_row(session, lease_scope(lease))
    require_lease(actual, lease, await db_now(session), execute=True)
    author, verifier = await engineering_work_pair(session, control, lease)
    require_acceptance(verifier.task_id == actual.task_id)
    current_author = await ManagementPlanStore.current_binding(
        session, lease.company_id, author.task_id
    )
    current_verifier = await ManagementPlanStore.current_binding(
        session, lease.company_id, verifier.task_id
    )
    require_acceptance(current_author is not None and current_verifier is not None)
    assert current_author is not None and current_verifier is not None
    receipt = await actual_receipt(session, author, author_action_id)
    target = VerificationSpec(
        company_id=lease.company_id,
        author=current_author.child.binding,
        verifier=current_verifier.child.binding,
        action_id=author_action_id,
        proposal_sha256=receipt.proposal_hash,
        receipt_id=receipt.receipt_id,
        receipt_sha256=canonical_sha256(receipt),
        work_snapshot_sha256=author.registration_hash,
        criterion_ids=ENGINEERING_CRITERIA,
        artifacts=await receipt_artifacts(session, receipt),
        check_recipe=ENGINEERING_RECIPE,
    )
    require_lease(actual, lease, await db_now(session), execute=True)
    return target
