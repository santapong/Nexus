"""Current owner metadata and protected candidate/replay reads; no SDK or new allowance.

Cohesion exception: owner, permanent dispatch, current/issued queue metadata and
final original-owner cutoff stay in the same locked read; splitting this file's
read boundary would obscure which native facts authorize descriptive replay.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy import select, text

from nexus.company.access import CompanyControlScope
from nexus.company.management.control_support import db_clock
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.owner_view_approvals import action_audit
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.planning_proposal_bridge import map_content
from nexus.company.management.planning_source_reader import PlanningSource
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.scheduling_queue import BINDING
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import effect_record
from nexus.execution.model_workflow_identity import (
    require_current_model_binding,
    require_issued_model_binding,
)
from nexus.execution.planning_dispatch import PlanningDispatchRecord
from nexus.execution.planning_lifecycle_bindings import PlanningBundle, owner_locked, stored_plans
from nexus.execution.planning_lifecycle_contracts import (
    PlanningCandidateReview,
    PlanningLifecycleRead,
    PlanningLifecycleStatus,
)
from nexus.execution.planning_services import REGISTRATION
from nexus.execution.runtime_contracts import EffectState
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import JournalAction

if TYPE_CHECKING:
    from nexus.execution.planning_lifecycle import PlanningLifecycle


def _dispatch(
    row: SegmentDispatch, action: JournalAction, lifecycle: PlanningLifecycle
) -> PlanningDispatchRecord:
    command = SegmentCommand.model_validate_json(row.binding_json)
    bound = lifecycle.config.admission.slots[0].child.binding
    if (
        (
            command.company_id,
            command.task_id,
            command.trace_id,
            command.actor_id,
            command.workspace_id,
            command.run_id,
            command.action_id,
        )
        != (
            bound.company_id,
            bound.task_id,
            bound.trace_id,
            bound.actor_id,
            bound.workspace_id,
            bound.run_id,
            action.id,
        )
        or (row.company_id, row.action_id, row.task_id, row.run_id, row.segment_id, row.workflow_id)
        != (
            command.company_id,
            command.action_id,
            command.task_id,
            command.run_id,
            command.segment_id,
            command.workflow_id,
        )
        or action.state != "authorized"
        or action.consumed_at is None
    ):
        raise ManagementDeniedError("Planning permanent dispatch metadata differs")
    return PlanningDispatchRecord(
        command=command, workflow_id=command.workflow_id, disposition="existing"
    )


async def existing_dispatch(
    lifecycle: PlanningLifecycle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    expected_hash: str,
    end_us: int,
) -> tuple[PlanningDispatchRecord | None, int]:
    async with management_owner_transaction(
        lifecycle.factory, scope, owner.identity, allow_paused=True
    ) as (session, control, _):
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
        row = await session.get(SegmentDispatch, (scope.company_id, action_id))
        action = await session.get(JournalAction, action_id)
        if action is None or action.company_id != scope.company_id:
            raise ManagementDeniedError("Planning native action is unavailable")
        audit = await action_audit(session, action)
        if audit.proposal_sha256 != expected_hash:
            raise ManagementDeniedError("Planning native action hash changed")
        result = _dispatch(row, action, lifecycle) if row is not None else None
        if result is not None:
            command = result.command
            work = await session.get(ExecutionWork, (scope.company_id, command.task_id))
            native = LedgerScope(
                company_id=scope.company_id,
                principal_id=command.actor_id,
                task_id=command.task_id,
                trace_id=command.trace_id,
            )
            if (
                work is None
                or (await dispatched_binding(session, work, native, command.segment_id)) != command
            ):
                raise ManagementDeniedError("Planning permanent native dispatch differs")
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
            projected = cast(Mapping[str, object] | None, queue)
            effect = await session.get(EffectIntent, (scope.company_id, action_id))
            if effect is None:
                require_current_model_binding(command, projected, REGISTRATION)
            else:
                if effect.intent_fence > work.fence or snapshot(work).counters.model_requests < 1:
                    raise ManagementDeniedError("Planning issued replay lacks its original attempt")
                require_issued_model_binding(
                    command, projected, REGISTRATION, effect_record(effect), audit.proposal_sha256
                )
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
    require_time(end_us)
    return result, end_us


async def status(
    lifecycle: PlanningLifecycle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    goal_id: UUID,
    end_us: int,
) -> PlanningLifecycleRead[PlanningLifecycleStatus]:
    """Native metadata only; a stored dispatch without a known effect is unconfirmed."""
    if goal_id != lifecycle.config.goal.goal_id:
        raise ManagementDeniedError("Planning goal is not configured")
    async with management_owner_transaction(
        lifecycle.factory, scope, owner.identity, allow_paused=True
    ) as (session, control, _):
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
        base, target, head = await stored_plans(session, lifecycle.config)
        bound = lifecycle.config.admission.slots[0].child.binding
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
            raise ManagementDeniedError("Planning has ambiguous native action history")
        action = actions[0] if actions else None
        audit = await action_audit(session, action) if action is not None else None
        if action is not None and (
            work is None or audit is None or audit.actor_id != bound.actor_id
        ):
            raise ManagementDeniedError("Planning native action/work is inconsistent")
        dispatch = (
            await session.get(SegmentDispatch, (scope.company_id, action.id))
            if action is not None
            else None
        )
        queued = (
            _dispatch(dispatch, action, lifecycle)
            if dispatch is not None and action is not None
            else None
        )
        effect = (
            await session.get(EffectIntent, (scope.company_id, action.id))
            if action is not None
            else None
        )
        native_state: EffectState | None = None
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
            ) or effect.state not in {"intent", "outcome_unknown", "succeeded", "failed"}:
                raise ManagementDeniedError("Planning native effect metadata differs")
            native_state = cast(EffectState, effect.state)
        if head is not None and head.state not in {"proposed", "approved", "revoked"}:
            raise ManagementDeniedError("Planning native head state is unsupported")
        current = next(
            (
                row
                for row in (base, target)
                if row is not None
                and head is not None
                and row.plan_revision_id == head.current_revision_id
            ),
            None,
        )
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
        value = PlanningLifecycleStatus(
            company_id=scope.company_id,
            goal=lifecycle.config.goal,
            plan_id=lifecycle.config.admission.plan_id,
            observed_at=await db_clock(session),
            bootstrap=plan_reference(base) if base else None,
            current=plan_reference(current) if current else None,
            current_state=cast(
                Literal["proposed", "approved", "revoked"] | None, head.state if head else None
            ),
            action_id=action.id if action else None,
            proposal_sha256=audit.proposal_sha256 if audit else None,
            action_state=audit.state if audit else None,
            owner_decision=audit.owner_decision.decision
            if audit and audit.owner_decision
            else None,
            owner_decision_expires_at=audit.owner_decision.expires_at
            if audit and audit.owner_decision
            else None,
            work_state=snapshot(work).state if work else None,
            workflow_id=queued.workflow_id if queued else None,
            segment_id=dispatch.segment_id if dispatch else None,
            native_state=native_state,
            formal_proposal=plan_reference(target) if target else None,
            resources_pending=bool(lifecycle.pending_owners()),
        )
    lifecycle.require_composition()
    require_time(end_us)
    return PlanningLifecycleRead(value, end_us)


async def _source(
    lifecycle: PlanningLifecycle,
    bundle: PlanningBundle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    end_us: int,
) -> tuple[PlanningSource, int]:
    """Use the actual concrete locked reader for both r1 and already-approved exact r2."""
    bundle.require_composition()
    lifecycle.require_composition()
    require_time(end_us)
    async with management_owner_transaction(
        lifecycle.factory, scope, owner.identity, allow_paused=False
    ) as (session, control, _):
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
        target_id = bundle.target.plan_revision_id if bundle.target is not None else None
        # Existing load() takes this same CC mutex and calls _load_locked. Passing
        # the actual stored target here supports approved-r2 replay without a fake base/CAS.
        source = await bundle.reader._load_locked(
            session, control, scope, owner.identity, action_id, target_id, end_us
        )
        if (
            bundle.target is not None
            and map_content(source.content, source.origin, bundle.reader.template)
            != bundle.target.payload
        ):
            raise ManagementDeniedError(
                "Stored target differs from exact protected candidate/origin"
            )
        if bundle.target is not None:
            current_target = await session.get(
                ManagementPlanRevision, (scope.company_id, bundle.target.plan_revision_id)
            )
            if current_target is None or plan_record(current_target) != bundle.target:
                raise ManagementDeniedError("Stored target changed during protected candidate READ")
        windows = tuple(
            row.expires_at for row in source.manifest.contributors if row.expires_at is not None
        )
        windows += tuple(
            row.fresh_until for row in source.manifest.source_heads if row.fresh_until is not None
        )
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
        before = clock_us()
        now = await db_clock(session)
        end_us = min(
            (end_us, *(before + (value - now) // timedelta(microseconds=1) for value in windows))
        )
    bundle.require_composition()
    lifecycle.require_composition()
    require_time(end_us)
    return source, end_us


async def candidate(
    lifecycle: PlanningLifecycle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    expected_head: UUID,
    end_us: int,
) -> PlanningLifecycleRead[PlanningCandidateReview]:
    bundle, end_us = await lifecycle._bundle(scope, owner, end_us)
    if expected_head not in {bundle.base.plan_revision_id, bundle.head_revision_id}:
        raise ManagementDeniedError("Planning candidate expected head differs")
    source, end_us = await _source(lifecycle, bundle, scope, owner, action_id, end_us)
    value = PlanningCandidateReview(
        company_id=scope.company_id,
        action_id=action_id,
        goal=lifecycle.config.goal,
        bootstrap=plan_reference(bundle.base),
        origin=source.origin,
        content=source.content,
        manifest=source.manifest,
        model_recorded_at=source.model_recorded_at,
    )
    require_time(end_us)
    return PlanningLifecycleRead(value, end_us)


async def replay_target(
    lifecycle: PlanningLifecycle,
    bundle: PlanningBundle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    end_us: int,
) -> tuple[PlanRevision | None, int]:
    if bundle.target is None:
        return None, end_us
    if (
        bundle.target.payload.planning_origin is None
        or bundle.target.payload.planning_origin.action_id != action_id
    ):
        raise ManagementDeniedError("Stored target belongs to another planning action")
    _, end_us = await _source(lifecycle, bundle, scope, owner, action_id, end_us)
    return bundle.target, end_us


async def approval_store(
    lifecycle: PlanningLifecycle,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    revision_id: UUID,
    exact_hash: str,
    end_us: int,
) -> tuple[ManagementPlanStore, int]:
    async with management_owner_transaction(
        lifecycle.factory, scope, owner.identity, allow_paused=True
    ) as (session, control, _):
        end_us = await owner_locked(
            lifecycle.services, lifecycle.config, session, control, scope, owner, end_us
        )
        row = await session.get(ManagementPlanRevision, (scope.company_id, revision_id))
        if row is None:
            raise ManagementDeniedError("Planning approval target is unavailable")
        record = plan_record(row)
        if record.sha256 != exact_hash or record.plan_id != lifecycle.config.admission.plan_id:
            raise ManagementDeniedError("Planning approval exact target/hash differs")
        bootstrap = record.payload == lifecycle.config.admission.payload("planning")
        if not bootstrap and record.payload.planning_origin is None:
            raise ManagementDeniedError("Planning target has no protected origin")
    if bootstrap:
        plans = ManagementPlanStore(
            lifecycle.factory,
            lifecycle.services.management.catalog,
            source_freshness=lifecycle.services.management.freshness,
        )
    else:
        bundle, end_us = await lifecycle._bundle(scope, owner, end_us)
        if bundle.target is None or bundle.target != record:
            raise ManagementDeniedError("Planning approval differs from actual stored target")
        plans = bundle.plans
    require_time(end_us)
    return plans, end_us
