"""Current native M3 actor/issued-intent/authority gates; no grant or counter consumption."""

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import ChildAllocation
from nexus.execution.effect_support import effect_row
from nexus.execution.management_checks import (
    ManagementArtifactFreshness,
    require_management_execution,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, lease_scope, require_lease
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.authorization_source import require_action_authority
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.standing_contracts import StandingGrant
from nexus.harness.standing_models import StandingAuthorityGrant


def generated_scope(lease: ExecutionLease, action_id: UUID) -> BrainReadScope:
    """Only audit identity is derived; current native work/identity still must match."""
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=lease.actor_id,
        operation_id=uuid5(action_id, "generated-artifact-publication:v1"),
        trace_id=lease.trace_id,
        task_id=lease.task_id,
        task_trace_id=lease.trace_id,
        actor_id=lease.actor_id,
    )


async def action_expiry(session: AsyncSession, record: JournalAction) -> datetime:
    """Capture exact/standing temporal authority for the final pure clock check."""
    if record.approval_json is not None:
        return ApprovalDecision.model_validate_json(record.approval_json).expires_at
    source = await session.get(ActionAuthority, (record.company_id, record.id))
    if source is None:
        raise ExecutionDeniedError("Native artifact authority source is unavailable")
    grant = await session.get(StandingAuthorityGrant, source.grant_id)
    if grant is None or grant.company_id != record.company_id:
        raise ExecutionDeniedError("Native artifact standing authority is unavailable")
    return StandingGrant.model_validate_json(grant.snapshot_json).expires_at


async def require_generated_actor(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action_id: UUID,
    catalog: PlanAdmissionCatalog,
    reader: BoundedArtifactReader,
    freshness: ManagementArtifactFreshness,
    *,
    known: bool,
) -> tuple[ActionProposal, datetime, ChildAllocation]:
    """Recheck actual lease/issued fence/native managed actor and immutable authority pins."""
    # This >50-line bound stays together so exact work/action/fence/authority share the mutex.
    require_lease(work, lease, await db_now(session), execute=True)
    if await ManagementPlanStore.managed_kind(session, work.company_id, work.task_id) != "managed":
        raise ExecutionDeniedError("Generated artifacts require actual current managed child work")
    binding = await ManagementPlanStore.current_binding(session, work.company_id, work.task_id)
    if binding is None:
        raise ExecutionDeniedError("Generated current native child binding is unavailable")
    intent = await effect_row(session, work, action_id)
    record = await session.get(JournalAction, action_id)
    if record is None or record.company_id != work.company_id or record.state != "authorized":
        raise ExecutionDeniedError("Native artifact exact issued action is unavailable")
    action = ActionProposal.model_validate_json(record.proposal_json)
    if (
        intent.intent_fence != lease.fence
        or intent.attempt_kind != "tool_attempts"
        or intent.proposal_hash != record.proposal_hash
        or action_hash(action) != record.proposal_hash
        or action.actor_id != lease.actor_id
        or (action.task_id, action.trace_id) != (work.task_id, work.trace_id)
        or (not known and (intent.state != "intent" or intent.receipt_json is not None))
    ):
        raise ExecutionDeniedError("Native artifact requires its exact already-issued actor intent")
    await require_action_authority(
        session,
        control,
        record,
        lease_scope(lease),
        identity,
        await db_now(session),
        action.preconditions,
    )
    await require_management_execution(
        session, control, work, identity, catalog, reader, freshness, action, "tool_attempts"
    )
    expires = await action_expiry(session, record)
    return action, expires, binding.child
