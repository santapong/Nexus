"""Compose native action dispatch and actual DBOS SQL enqueue in the caller's transaction."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.control_support import db_clock
from nexus.company.management.scheduling_contracts import ScheduledWork, WorkflowRegistration
from nexus.company.management.scheduling_projection import projection
from nexus.company.management.scheduling_reads import action_kind
from nexus.company.management.scheduling_support import SchedulerServices, SchedulingCandidate
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_store import reserve_dispatch
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import AttemptKind
from nexus.execution.runtime_store import next_segment_id
from nexus.execution.runtime_support import require_runtime_scope, snapshot
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget
from nexus.harness.journal_reservations import require_current_work_caps

ENQUEUE = text("""
SELECT dbos.enqueue_workflow(
 workflow_name => :workflow_name, queue_name => :queue_name,
 positional_args => ARRAY[CAST(:payload AS json)], workflow_id => :workflow_id,
 app_version => :version, application_name => :application_name)
""")
BINDING = text("""
SELECT ws.name,ws.queue_name,ws.application_version,ws.application_name,
       ws.serialization,wi.inputs
FROM dbos.workflow_status ws LEFT JOIN dbos.workflow_input wi
 ON wi.workflow_uuid=ws.workflow_uuid WHERE ws.workflow_uuid=:workflow_id
FOR UPDATE OF ws
""")


def workflow_registration(
    services: SchedulerServices, name: str, version: str
) -> WorkflowRegistration:
    """Only constructor-registered exact workflow ABI can receive portable action commands."""
    selected = next(
        (
            row
            for row in services.policy.workflows
            if (row.workflow_name, row.workflow_version) == (name, version)
        ),
        None,
    )
    if selected is None:
        raise ManagementDeniedError("Managed workflow ABI is not registered for scheduling")
    return selected


async def _current_authority(
    session: AsyncSession,
    control: CompanyControl,
    candidate: SchedulingCandidate,
    services: SchedulerServices,
) -> None:
    work, action, identity, scope = (
        candidate.work,
        candidate.action,
        candidate.identity,
        candidate.scope,
    )
    if action is None or identity is None or scope is None:
        raise ManagementDeniedError("Scheduling lacks actual actor/action authority")
    await require_runtime_scope(
        session, control, scope, identity, allow_inactive=False, owner_read=False
    )
    proposed = ActionProposal.model_validate_json(action.proposal_json)
    kind = action_kind(proposed.tool)
    await require_management_execution(
        session,
        control,
        work,
        identity,
        services.catalog,
        services.artifacts,
        services.freshness,
        proposed,
        kind,
    )
    resources = await services.resources.current(
        session, candidate.projection.eligibility.work, proposed, identity
    )
    await require_effect_authority(
        session, control, work, action.id, await db_clock(session), resources, scope, identity
    )
    await _capacity(session, control, candidate, kind)


async def _capacity(
    session: AsyncSession,
    control: CompanyControl,
    candidate: SchedulingCandidate,
    kind: AttemptKind,
) -> None:
    work, action, scope = candidate.work, candidate.action, candidate.scope
    if action is None or scope is None:
        raise ManagementDeniedError("Scheduling capacity lacks actual action scope")
    await require_current_work_caps(session, control, scope)
    hold = await session.get(CostHold, action.id)
    day_id = billing_day(await db_clock(session))
    day = await session.get(DailyBudget, (work.company_id, day_id))
    transfer = hold.amount_usd if hold is not None and hold.day != day_id else 0
    if (
        hold is None
        or (day.held_usd + day.spent_usd if day else 0) + transfer > control.daily_cap_usd
    ):
        raise ManagementDeniedError("Current day cannot fund the unissued scheduling reservation")
    if (
        work.worker_id is not None
        or work.state not in {"eligible", "awaiting_approval"}
        or getattr(work, f"{kind}_used") + getattr(work, f"{kind}_delegated")
        >= getattr(work, f"{kind}_limit")
    ):
        raise ManagementDeniedError("Scheduling cannot acquire or replace execution capacity")


async def enqueue_candidate(
    session: AsyncSession,
    control: CompanyControl,
    candidate: SchedulingCandidate,
    services: SchedulerServices,
) -> ScheduledWork:
    """No counter/hold/lease changes; a consumed exact action remains independently gated."""
    if not session.in_transaction() or candidate.binding is None or candidate.action is None:
        raise ManagementDeniedError("Scheduling requires its actual company transaction/action")
    if candidate.projection.eligibility.state != "eligible":
        return candidate.projection
    await _current_authority(session, control, candidate, services)
    row = candidate.work
    registration = workflow_registration(services, row.workflow_name, row.workflow_version)
    command = SegmentCommand(
        company_id=row.company_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        actor_id=row.actor_id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        action_id=candidate.action.id,
        segment_id=next_segment_id(snapshot(row)),
    )
    await reserve_dispatch(
        session,
        command,
        workflow_name=registration.workflow_name,
        workflow_version=registration.workflow_version,
    )
    await _enqueue_exact(session, command, registration)
    # Queue SQL may cross an authority/source expiry; no immutable receipt/cursor
    # can acknowledge an expired admission merely because its first check passed.
    await _current_authority(session, control, candidate, services)
    result = projection(row, candidate.binding, "eligible", "ready")
    return ScheduledWork.model_validate_json(
        result.model_copy(
            update={
                "action_id": command.action_id,
                "dispatch": "enqueued",
                "segment_id": command.segment_id,
                "workflow_id": command.workflow_id,
            }
        ).model_dump_json()
    )


async def _enqueue_exact(
    session: AsyncSession, command: SegmentCommand, registration: WorkflowRegistration
) -> None:
    payload = command.model_dump_json()
    result = await session.scalar(
        ENQUEUE,
        {
            "workflow_name": registration.workflow_name,
            "queue_name": registration.queue_name,
            "payload": json.dumps(payload),
            "workflow_id": command.workflow_id,
            "version": registration.workflow_version,
            "application_name": registration.application_name,
        },
    )
    stored = (
        (await session.execute(BINDING, {"workflow_id": command.workflow_id}))
        .mappings()
        .one_or_none()
    )
    if stored is None or (
        stored["name"],
        stored["queue_name"],
        stored["application_version"],
        stored["application_name"],
        stored["serialization"],
    ) != (
        registration.workflow_name,
        registration.queue_name,
        registration.workflow_version,
        registration.application_name,
        "portable_json",
    ):
        raise ManagementDeniedError("Stored DBOS workflow ABI differs from native scheduling")
    try:
        inputs = json.loads(stored["inputs"])
    except (TypeError, ValueError) as exc:
        raise ManagementDeniedError("Stored DBOS scheduling input is unavailable") from exc
    if inputs != {"positionalArgs": [payload], "namedArgs": {}} or result != command.workflow_id:
        raise ManagementDeniedError("Stored DBOS workflow input/identity differs")
