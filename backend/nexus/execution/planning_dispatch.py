"""Current true-actor READ then atomic approval/hold/fixed planning enqueue; no SDK call."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.management.planning_prepared_contracts import (
    StoredPlanningRequest,
    prepared_reference,
)
from nexus.company.management.scheduling_queue import _enqueue_exact
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.dispatch_store import reserve_dispatch
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.planning_context import quote_locked, route_prepared, state_locked
from nexus.execution.planning_services import (
    REGISTRATION,
    VERSION,
    WORKFLOW,
    PlanningOperation,
    PlanningServices,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_store import next_segment_id
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_authorization import authorize_registered_pending_locked
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, JournalAction
from nexus.harness.journal_reservations import require_current_work_caps
from nexus.harness.journal_submission import pending_action_record
from nexus.harness.model_authorizer_contracts import model_action_parameters


class PlanningDispatchRecord(ValueContract):
    command: SegmentCommand
    workflow_id: str
    disposition: Literal["existing", "enqueued"]
    company_completed: Literal[False] = False


def ledger(scope: BrainReadScope) -> LedgerScope:
    if scope.task_id is None or scope.task_trace_id is None or scope.actor_id != scope.principal_id:
        raise ValueError("Planning dispatch requires the actual registered actor scope")
    return LedgerScope(
        company_id=scope.company_id,
        principal_id=scope.principal_id,
        task_id=scope.task_id,
        trace_id=scope.task_trace_id,
    )


async def _existing(
    operation: PlanningOperation,
    scope: BrainReadScope,
    action_id: UUID,
    expected_hash: str,
) -> SegmentCommand | None:
    credential = operation.credential
    assert credential is not None
    native = ledger(scope)
    async with runtime_transaction(
        operation.services.factory,
        native,
        credential.identity,
        allow_paused=True,
        allow_inactive=True,
    ) as (session, _, _):
        work = await execution_row(session, native)
        row = await session.get(SegmentDispatch, (scope.company_id, action_id))
        if row is None:
            return None
        action = await session.get(JournalAction, action_id)
        if (
            action is None
            or action.proposal_hash != expected_hash
            or action_hash(pending_action_record(action).proposal) != expected_hash
        ):
            raise ValueError("Planning existing native action hash differs")
        command = await dispatched_binding(session, work, native, row.segment_id)
        if (work.workflow_name, work.workflow_version) != (
            WORKFLOW,
            VERSION,
        ) or command.action_id != action_id:
            raise ValueError("Planning existing dispatch belongs to another workflow/action")
        operation.require_current()
    operation.require_current()
    return command


async def _fresh(
    operation: PlanningOperation,
    session: AsyncSession,
    control: CompanyControl,
    loaded: StoredPlanningRequest,
    expected_hash: str,
) -> tuple[ExecutionWork, ActionRecord, tuple[ResourceRevision, ...], CostQuote]:
    credential, services = operation.credential, operation.services
    assert credential is not None
    prepared = loaded.prepared
    scope = ledger(prepared.scope)
    state = await state_locked(operation, session, control, prepared.scope)
    work = await execution_row(session, scope)
    row = await session.get(JournalAction, prepared.request.action_id)
    if row is None:
        raise ValueError("Planning dispatch lacks the actual native pending action")
    record = pending_action_record(row)
    call, proposal = prepared.request, record.proposal
    if (
        (state.goal, state.plan_id, state.head)
        != (
            prepared.binding.goal,
            prepared.binding.plan_id,
            prepared.binding.expected_plan_revision_id,
        )
        or (proposal.company_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
        != (call.company_id, call.task_id, call.trace_id, call.actor_id)
        or record.proposal_hash != expected_hash
        or action_hash(proposal) != expected_hash
        or proposal.parameters != model_action_parameters(call, services.recipe)
        or (proposal.tool, proposal.tool_version, proposal.resource)
        != ("model.request.v1", "v1", f"model:{services.registry_id}")
        or prepared_reference(proposal) != loaded.reference
        or row.consumed_at is not None
        or row.state != "awaiting_approval"
        or work.worker_id is not None
        or work.lease_until is not None
        or work.state != "awaiting_approval"
        or work.waiting_action_id != call.action_id
        or await session.get(EffectIntent, (work.company_id, call.action_id)) is not None
        or await session.get(CostHold, call.action_id) is not None
    ):
        raise ValueError("Planning pending registration/preparation/approval capacity differs")
    if (
        services.estimator.estimate(call, services.management.catalog.models, services.recipe)
        != prepared.input_estimate
    ):
        raise ValueError("Planning reviewed input proof differs from the original server estimator")
    resources = await services.contexts.revalidate_context(
        session,
        control,
        prepared.scope,
        credential.identity,
        prepared.context.manifest,
        await db_now(session),
    )
    resources = (*resources, loaded.reference.condition)
    if set(proposal.preconditions) != set(resources):
        raise ValueError("Planning current Brain/prepared resources differ from owner approval")
    selected = await quote_locked(services, session, control, work, prepared, await db_now(session))
    if proposal.estimated_cost_usd != selected.quote.amount_usd:
        raise ValueError("Planning current model quotation differs from owner-approved maximum")
    operation.require_admission()
    return work, record, resources, selected.quote


async def _authorize(
    operation: PlanningOperation,
    loaded: StoredPlanningRequest,
    expected_hash: str,
) -> PlanningDispatchRecord:
    credential, services = operation.credential, operation.services
    assert credential is not None
    prepared, scope = loaded.prepared, ledger(loaded.prepared.scope)
    async with runtime_transaction(services.factory, scope, credential.identity) as (
        session,
        control,
        _,
    ):
        work, original, resources, quote = await _fresh(
            operation, session, control, loaded, expected_hash
        )
        operation.require_admission()
        await authorize_registered_pending_locked(
            session,
            control,
            scope,
            credential.identity,
            prepared.request.action_id,
            await db_now(session),
            resources,
        )
        command = SegmentCommand(
            company_id=work.company_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            actor_id=work.actor_id,
            workspace_id=work.workspace_id,
            run_id=work.run_id,
            action_id=prepared.request.action_id,
            segment_id=next_segment_id(snapshot(work)),
        )
        operation.require_admission()
        await reserve_dispatch(session, command, workflow_name=WORKFLOW, workflow_version=VERSION)
        operation.require_admission()
        await _enqueue_exact(session, command, REGISTRATION)
        # Every post-queue check remains in this same CC-first transaction.
        state = await state_locked(operation, session, control, prepared.scope)
        if (state.goal, state.plan_id, state.head) != (
            prepared.binding.goal,
            prepared.binding.plan_id,
            prepared.binding.expected_plan_revision_id,
        ):
            raise ValueError("Planning current goal/head changed during enqueue")
        final_resources = await services.contexts.revalidate_context(
            session,
            control,
            prepared.scope,
            credential.identity,
            prepared.context.manifest,
            await db_now(session),
        )
        if {*final_resources, loaded.reference.condition} != set(resources):
            raise ValueError("Planning source resources changed during enqueue")
        now = await db_now(session)
        await require_effect_authority(
            session, control, work, command.action_id, now, resources, scope, credential.identity
        )
        await require_current_work_caps(session, control, scope)
        hold = await session.get(CostHold, command.action_id)
        now = await db_now(session)
        day = await session.get(DailyBudget, (work.company_id, billing_day(now)))
        anchor = clock_us()
        final_now = await db_now(session)
        if (
            hold is None
            or hold.state != "held"
            or hold.actual_usd is not None
            or hold.amount_usd != quote.amount_usd
            or billing_day(now) != billing_day(final_now)
            or original.approval is None
            or not original.approval.issued_at <= final_now < original.approval.expires_at
            or route_prepared(services, prepared, work, control, hold.amount_usd, final_now).quote
            != quote
            or (day.held_usd + day.spent_usd if day else 0)
            + (hold.amount_usd if hold.day != billing_day(now) else 0)
            > control.daily_cap_usd
        ):
            raise ValueError("Planning final reservation or financial window changed")
        credential.require_time(final_now)
        operation.shorten(final_now, anchor, (credential.expires_at, original.approval.expires_at))
        operation.require_admission()
        result = PlanningDispatchRecord(
            command=command, workflow_id=command.workflow_id, disposition="enqueued"
        )
    operation.require_current()
    return result


async def dispatch(
    services: PlanningServices,
    scope: BrainReadScope,
    action_id: UUID,
    expected_hash: str,
    *,
    end_us: int,
) -> PlanningDispatchRecord:
    """No execute claim before authorization: actual actor READ derives exact private resources."""
    if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("Planning expected native action hash is invalid")
    ledger(scope)
    operation = PlanningOperation(services, "dispatch:" + str(uuid4()), end_us)
    result: PlanningDispatchRecord | None = None
    try:
        credential = await operation.call(services.identities.current())
        operation.credential = credential
        if (scope.principal_id, scope.workspace_id) != (
            credential.identity.principal_id,
            credential.identity.workspace_id,
        ):
            raise ValueError("Planning dispatch requires its actual actor identity")
        existing = await operation.call(_existing(operation, scope, action_id, expected_hash))
        if existing is not None:
            result = PlanningDispatchRecord(
                command=existing, workflow_id=existing.workflow_id, disposition="existing"
            )
        else:
            loaded = await operation.call(
                services.prepared.load_actor(
                    scope, credential.identity, action_id, end_us=operation.end
                )
            )
            operation.end = min(operation.end, loaded.read_end_us)
            operation.require_admission()
            result = await operation.call(_authorize(operation, loaded, expected_hash))
        result.model_dump_json()
        operation.require_current()
    except BaseException as first:
        operation.first = operation.first or first
    operation.finish()
    if operation.first is not None:
        raise operation.first
    assert result is not None
    return result
