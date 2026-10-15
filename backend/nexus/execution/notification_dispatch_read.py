"""Configured same-company native dispatch metadata; no lease, body or provider permit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, text

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import ValueContract
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.ledger_rules import stable_idempotency_key
from nexus.company.notifications.proposals import NOTIFICATION_TOOL, NotificationDispatchParameters
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_profile_checks import (
    require_notification_ancestry,
    require_zero_model_ancestry,
)
from nexus.execution.notification_worker_services import (
    NOTIFICATION_QUEUE,
    NOTIFICATION_VERSION,
    NOTIFICATION_WORKFLOW,
    NotificationDispatchWorkerServices,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import (
    db_now,
    registration_digest,
    require_runtime_scope,
    snapshot,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction

_DENIED = "Notification durable dispatch metadata is unavailable"


@dataclass(frozen=True, slots=True)
class NotificationDispatchBinding:
    """Verified metadata is not a reusable capability; every effect rechecks actual native state."""

    command: SegmentCommand
    binding: RunBinding
    action: ActionProposal
    draft_id: UUID


class NotificationQueueRecord(ValueContract):
    """Decode actual SQL row fields, never a caller's assertion of active execution."""

    name: Literal["internal.owner-notification"]
    queue_name: str | None
    application_version: Literal["v1"]
    application_name: Literal["nexus-owner-notifications"]
    serialization: Literal["portable_json"]
    status: str
    inputs: str


def require_notification_command(
    binding: RunBinding,
    action: ActionProposal,
    command: SegmentCommand,
    resource_symbol: str,
) -> NotificationDispatchParameters:
    """Whole immutable identity and closed action parameters precede selection of any draft."""
    if (
        (binding.workflow_name, binding.workflow_version, binding.model_profile)
        != (NOTIFICATION_WORKFLOW, NOTIFICATION_VERSION, "notification.native.v1")
        or (
            binding.company_id,
            binding.task_id,
            binding.trace_id,
            binding.actor_id,
            binding.workspace_id,
            binding.run_id,
        )
        != (
            command.company_id,
            command.task_id,
            command.trace_id,
            command.actor_id,
            command.workspace_id,
            command.run_id,
        )
        or (action.company_id, action.task_id, action.trace_id, action.actor_id, action.action_id)
        != (
            command.company_id,
            command.task_id,
            command.trace_id,
            command.actor_id,
            command.action_id,
        )
        or (action.tool, action.tool_version, action.resource)
        != (NOTIFICATION_TOOL, NOTIFICATION_VERSION, resource_symbol)
    ):
        raise ExecutionDeniedError(_DENIED)
    return NotificationDispatchParameters.model_validate_json(json.dumps(action.parameters))


def require_queue_identity(
    queue: NotificationQueueRecord,
    command: SegmentCommand,
    *,
    issued: bool,
) -> None:
    """Issued is internal actual-row classification; this pure comparison issues no authority."""
    if json.loads(queue.inputs) != {"positionalArgs": [command.model_dump_json()], "namedArgs": {}}:
        raise ExecutionDeniedError(_DENIED)
    if issued:
        if queue.queue_name not in {None, NOTIFICATION_QUEUE} or queue.status not in {
            "ENQUEUED",
            "PENDING",
            "SUCCESS",
            "ERROR",
            "CANCELLED",
            "DELAYED",
            "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
        }:
            raise ExecutionDeniedError(_DENIED)
    elif queue.queue_name != NOTIFICATION_QUEUE or queue.status != "PENDING":
        raise ExecutionDeniedError(_DENIED)


async def read_notification_dispatch(
    services: NotificationDispatchWorkerServices,
    command: SegmentCommand,
    workflow_id: str,
    *,
    operation_guard: NotificationOperationGuard | None = None,
) -> NotificationDispatchBinding:
    """Read actual permanent identity under CC before resolving a genuine configured credential."""
    # Cohesive >50-line metadata boundary: native registration/journal/original
    # issuance and exact SDK input must refer to the same one configured company.
    services.require_enabled()
    if services.reads.facts.catalog.cycle_admission is not None:
        validate_cycle_catalog(
            services.reads.facts.catalog.cycle_admission, services.reads.facts.catalog
        )
        if type(operation_guard) is not NotificationOperationGuard:
            raise ExecutionDeniedError("Mixed notification requires its sealed operation guard")
        if operation_guard.reader is not services.reads.registrations:
            raise ExecutionDeniedError(_DENIED)
        configured = operation_guard.snapshot
        operation_guard.reader.require_current(configured)
    else:
        configured = services.reads.registrations.snapshot()
    services.reads.require_registration(configured)
    registered = configured.value.registration
    if command.company_id != registered.company_id or workflow_id != command.workflow_id:
        raise ExecutionDeniedError(_DENIED)
    mixed = services.reads.facts.catalog.cycle_admission is not None
    if mixed and any(
        getattr(command, key) != getattr(registered.sender, key)
        for key in ("company_id", "task_id", "trace_id", "run_id", "actor_id", "workspace_id")
    ):
        raise ExecutionDeniedError(_DENIED)
    async with services.reads.factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(registered.company_id), True))
        )
        if mixed:
            assert operation_guard is not None
            for key, scope_value in (
                ("nexus.workspace_id", operation_guard.witness.identity.workspace_id),
                ("nexus.principal_id", operation_guard.witness.identity.principal_id),
            ):
                await session.execute(select(func.set_config(key, str(scope_value), True)))
        control = await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == command.company_id)
            .with_for_update()
        )
        work = await session.get(ExecutionWork, (command.company_id, command.task_id))
        if control is None or work is None:
            raise ExecutionDeniedError(_DENIED)
        if mixed:
            assert operation_guard is not None
            current_scope = LedgerScope(
                company_id=registered.company_id,
                task_id=registered.sender.task_id,
                trace_id=registered.sender.trace_id,
                principal_id=operation_guard.witness.identity.principal_id,
            )
            operation_guard.require_time(await db_now(session))
            await require_runtime_scope(
                session,
                control,
                current_scope,
                operation_guard.witness.identity,
                allow_inactive=True,
                owner_read=False,
            )
        action_row = await session.get(JournalAction, command.action_id)
        if action_row is None:
            raise ExecutionDeniedError(_DENIED)
        if (action_row.company_id, action_row.task_id, action_row.trace_id, action_row.id) != (
            command.company_id,
            command.task_id,
            command.trace_id,
            command.action_id,
        ):
            raise ExecutionDeniedError(_DENIED)
        value = snapshot(work).registration
        if registration_digest(value) != work.registration_hash:
            raise ExecutionDeniedError(_DENIED)
        binding = RunBinding(
            company_id=work.company_id,
            workspace_id=work.workspace_id,
            actor_id=work.actor_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            run_id=work.run_id,
            workflow_name=work.workflow_name,
            workflow_version=work.workflow_version,
            model_profile=work.model_profile,
            model_registry_version=work.model_registry_version,
        )
        if binding != registered.sender or binding.actor_id != control.owner_id:
            raise ExecutionDeniedError(_DENIED)
        scope = LedgerScope(
            company_id=binding.company_id,
            principal_id=binding.actor_id,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
        )
        actual = await dispatched_binding(session, work, scope, command.segment_id)
        action = ActionProposal.model_validate_json(action_row.proposal_json)
        if actual != command or action_hash(action) != action_row.proposal_hash:
            raise ExecutionDeniedError(_DENIED)
        parameters = require_notification_command(
            binding, action, command, services.dispatcher.resource_symbol
        )
        if not mixed:
            await require_zero_model_ancestry(session, work)
        intent = await session.get(EffectIntent, (command.company_id, command.action_id))
        slot = await session.get(NotificationDispatchRow, (command.company_id, parameters.draft_id))
        if (intent is None) != (slot is None):
            raise ExecutionDeniedError(_DENIED)
        if intent is not None and slot is not None:
            require_issued_binding(work, action, parameters, intent, slot)
        if mixed:
            assert operation_guard is not None
            if intent is not None:
                from nexus.execution.mixed_notification_history import (
                    require_recorded_cycle_sender_family_locked,
                )

                await require_recorded_cycle_sender_family_locked(
                    session, control, work, operation_guard, command, services.reads.facts.catalog
                )
            else:
                admission = services.reads.facts.catalog.cycle_admission
                assert admission is not None
                await require_notification_ancestry(
                    session,
                    control,
                    work,
                    services.reads.facts.catalog,
                    admission.slots[-1].child,
                    identity=operation_guard.witness.identity,
                )
        saved = (
            (
                await session.execute(
                    text(
                        "SELECT ws.name,ws.queue_name,ws.application_version,ws.application_name,"
                        "ws.serialization,ws.status,wi.inputs FROM dbos.workflow_status ws "
                        "JOIN dbos.workflow_input wi ON wi.workflow_uuid=ws.workflow_uuid "
                        "WHERE ws.workflow_uuid=:workflow_id FOR UPDATE OF ws"
                    ),
                    {"workflow_id": command.workflow_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if saved is None:
            raise ExecutionDeniedError(_DENIED)
        queue = NotificationQueueRecord.model_validate(dict(saved))
        require_queue_identity(queue, command, issued=intent is not None)
        if mixed:
            assert operation_guard is not None
            await require_runtime_scope(
                session,
                control,
                scope,
                operation_guard.witness.identity,
                allow_inactive=intent is not None,
                owner_read=False,
            )
            final = await db_now(session)
            services.require_enabled()
            services.reads.require_registration(configured)
            if operation_guard.reader is not services.reads.registrations:
                raise ExecutionDeniedError(_DENIED)
            operation_guard.require_time(final)
    return NotificationDispatchBinding(command, binding, action, parameters.draft_id)


def require_issued_binding(
    work: ExecutionWork,
    action: ActionProposal,
    parameters: NotificationDispatchParameters,
    intent: EffectIntent,
    slot: NotificationDispatchRow,
) -> None:
    """Actual slot's original fence stays distinct from a later current recovery lease fence."""
    expected = (work.company_id, work.task_id, work.trace_id, work.run_id, action_hash(action))
    if (
        (intent.company_id, intent.task_id, intent.trace_id, intent.run_id, intent.proposal_hash)
        != expected
        or (slot.company_id, slot.task_id, slot.trace_id, slot.run_id, slot.proposal_sha256)
        != expected
        or intent.action_id != action.action_id
        or slot.action_id != action.action_id
        or intent.attempt_kind != "tool_attempts"
        or slot.attempt_kind != "tool_attempts"
        or slot.intent_fence != intent.intent_fence
        or slot.registration_sha256 != work.registration_hash
        or slot.draft_id != parameters.draft_id
        or slot.payload_sha256 != parameters.payload_sha256
        or slot.recipient_policy_sha256 != parameters.recipient_policy_sha256
        or slot.issued_by != work.actor_id
        or slot.operation_id != action.action_id
        or slot.audit_trace_id != work.trace_id
        or slot.idempotency_key != stable_idempotency_key(work.company_id, parameters.draft_id)
    ):
        raise ExecutionDeniedError(_DENIED)
