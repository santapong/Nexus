"""Owner native C metadata; issued replay never reacquires a C actor, body, lease or SDK.

Cohesion exception: complete owner/action/dispatch/queue observations stay in
their original locked transaction with their final owner and caller cutoff.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import select, text

from nexus.company.access import CompanyControlScope
from nexus.company.management.coding_prepared_contracts import prepared_reference
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_approvals import action_audit
from nexus.company.management.plan_models import ManagementPlanHead, ManagementPlanRevision
from nexus.company.management.planning_native_facts import require_time
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.scheduling_queue import BINDING
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_dispatch import CodingDispatchRecord
from nexus.execution.coding_history import require_workflow_binding
from nexus.execution.coding_lifecycle_bindings import owner_locked
from nexus.execution.coding_lifecycle_contracts import CodingLifecycleRead, CodingLifecycleStatus
from nexus.execution.coding_services import REGISTRATION
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import effect_record
from nexus.execution.model_workflow_identity import require_issued_model_binding
from nexus.execution.runtime_contracts import EffectState
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction
from nexus.harness.journal_submission import pending_action_record

if TYPE_CHECKING:
    from nexus.execution.coding_lifecycle import CodingLifecycle


async def existing_dispatch(
    lifecycle: CodingLifecycle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    expected_hash: str,
    end_us: int,
) -> tuple[CodingDispatchRecord | None, int]:
    """Read the exact immutable command before fresh C, source, Goal or model checks."""
    async with management_owner_transaction(
        lifecycle.factory, scope, owner.identity, allow_paused=True
    ) as (session, control, _):
        end_us = await owner_locked(lifecycle.services, session, control, scope, owner, end_us)
        action = await session.get(JournalAction, action_id)
        if action is None or action.company_id != scope.company_id:
            raise ManagementDeniedError("Coding native action unavailable")
        record = pending_action_record(action)
        proposal = record.proposal
        slot = lifecycle.config.admission.slots[1]
        bound = slot.child.binding
        if (
            record.proposal_hash != expected_hash
            or action_hash(proposal) != expected_hash
            or (proposal.company_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
            != (bound.company_id, bound.task_id, bound.trace_id, bound.actor_id)
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != (slot.tool.tool, slot.tool.tool_version, slot.tool.resource)
        ):
            raise ManagementDeniedError("Coding native action hash/role differs")
        prepared_reference(proposal)
        dispatch = await session.get(SegmentDispatch, (scope.company_id, action_id))
        effect = await session.get(EffectIntent, (scope.company_id, action_id))
        if dispatch is None:
            if effect is not None:
                raise ManagementDeniedError(
                    "Issued coding action lacks its original permanent dispatch"
                )
            result = None
        else:
            work = await session.get(ExecutionWork, (scope.company_id, bound.task_id))
            if work is None or action.state != "authorized" or action.consumed_at is None:
                raise ManagementDeniedError(
                    "Coding existing dispatch lacks original native work/consumption"
                )
            from nexus.harness.journal_contracts import LedgerScope

            native = LedgerScope(
                company_id=scope.company_id,
                principal_id=bound.actor_id,
                task_id=bound.task_id,
                trace_id=bound.trace_id,
            )
            command = await dispatched_binding(session, work, native, dispatch.segment_id)
            if (command.action_id, command.run_id, command.workspace_id) != (
                action_id,
                bound.run_id,
                bound.workspace_id,
            ):
                raise ManagementDeniedError("Coding permanent dispatch command differs")
            queue = (
                (
                    await session.execute(
                        text(BINDING.text.replace("FOR UPDATE OF ws", "")),
                        {"workflow_id": command.workflow_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if effect is None:
                require_workflow_binding(command, cast(Mapping[str, object] | None, queue))
            else:
                if effect.intent_fence > work.fence or snapshot(work).counters.model_requests < 1:
                    raise ManagementDeniedError("Coding issued replay lacks its original attempt")
                require_issued_model_binding(
                    command,
                    cast(Mapping[str, object] | None, queue),
                    REGISTRATION,
                    effect_record(effect),
                    record.proposal_hash,
                )
            result = CodingDispatchRecord(
                command=command, workflow_id=command.workflow_id, disposition="existing"
            )
        end_us = await owner_locked(lifecycle.services, session, control, scope, owner, end_us)
    require_time(end_us)
    return result, end_us


async def status(
    lifecycle: CodingLifecycle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    goal_id: UUID,
    end_us: int,
) -> CodingLifecycleRead[CodingLifecycleStatus]:
    """Metadata is descriptive even before r2 registration and after fresh actor expiry."""
    if goal_id != lifecycle.config.goal.goal_id:
        raise ManagementDeniedError("Coding Goal is not configured")
    async with management_owner_transaction(
        lifecycle.factory, scope, owner.identity, allow_paused=True
    ) as (session, control, _):
        end_us = await owner_locked(lifecycle.services, session, control, scope, owner, end_us)
        admission = lifecycle.config.admission
        bound = admission.slots[1].child.binding
        head = await session.get(ManagementPlanHead, (scope.company_id, admission.plan_id))
        row = (
            await session.get(ManagementPlanRevision, (scope.company_id, head.current_revision_id))
            if head
            else None
        )
        current = plan_record(row) if row else None
        work = await session.get(ExecutionWork, (scope.company_id, bound.task_id))
        actions = tuple(
            (
                await session.scalars(
                    select(JournalAction)
                    .where(
                        JournalAction.company_id == scope.company_id,
                        JournalAction.task_id == bound.task_id,
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(actions) > 1:
            raise ManagementDeniedError("Coding action history is ambiguous")
        action = actions[0] if actions else None
        audit = await action_audit(session, action) if action else None
        dispatch = (
            await session.get(SegmentDispatch, (scope.company_id, action.id)) if action else None
        )
        effect = await session.get(EffectIntent, (scope.company_id, action.id)) if action else None
        native: EffectState | None = None
        if effect is not None:
            if (
                effect.task_id,
                effect.trace_id,
                effect.run_id,
                effect.proposal_hash,
                effect.attempt_kind,
            ) != (
                bound.task_id,
                bound.trace_id,
                bound.run_id,
                audit.proposal_sha256 if audit else None,
                "model_requests",
            ):
                raise ManagementDeniedError("Coding effect metadata differs")
            if effect.state not in {"intent", "outcome_unknown", "succeeded", "failed"}:
                raise ManagementDeniedError("Coding native state invalid")
            native = cast(EffectState, effect.state)
        observed = await db_clock(session)
        value = CodingLifecycleStatus(
            company_id=scope.company_id,
            goal=admission.goal,
            current=plan_reference(current) if current else None,
            approved_r2=bool(
                head
                and head.state == "approved"
                and current
                and current.revision == 2
                and current.payload.coding_admission_sha256 == lifecycle.admission_sha256
            ),
            observed_at=observed,
            action_id=action.id if action else None,
            proposal_sha256=audit.proposal_sha256 if audit else None,
            action_state=audit.state if audit else None,
            work_state=snapshot(work).state if work else None,
            workflow_id=dispatch.workflow_id if dispatch else None,
            native_state=native,
            resources_pending=bool(
                lifecycle.services.pending_owners()
                or lifecycle.reads.pending_owners()
                or lifecycle.candidates.pending_owners()
            ),
        )
        end_us = await owner_locked(lifecycle.services, session, control, scope, owner, end_us)
    require_time(end_us)
    return CodingLifecycleRead(value, end_us)
