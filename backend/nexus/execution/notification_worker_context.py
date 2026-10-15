"""Reconstruct one actual notification context with genuine credential and same-dispatch lease."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_dispatch_read import read_notification_dispatch
from nexus.execution.notification_lease_recovery import (
    recover_notification_lease,
    require_current_credential,
)
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease


@dataclass(frozen=True, slots=True)
class NotificationContext:
    """Trusted live context is not checkpointable provider permission or private draft content."""

    command: SegmentCommand
    binding: RunBinding
    action: ActionProposal
    draft_id: UUID
    identity: VerifiedIdentity
    credential: AuthenticatedWorkerIdentity
    guard: NotificationOperationGuard
    lease: ExecutionLease


async def _mixed_operation_guard(
    services: NotificationDispatchWorkerServices, command: SegmentCommand, workflow_id: str
) -> NotificationOperationGuard:
    """Acquire one genuine witness against the original server declaration before metadata READ."""
    catalog = services.reads.facts.catalog
    configured = validate_cycle_catalog(catalog.cycle_admission, catalog)
    if configured is None or workflow_id != command.workflow_id:
        raise ExecutionDeniedError("Mixed notification declaration is unavailable")
    snapshot = services.reads.registrations.snapshot()
    services.reads.require_registration(snapshot)
    sender = snapshot.value.registration.sender
    command.require_scope(ledger_scope(sender))
    if sender != configured.slots[-1].child.binding or (
        sender.actor_id,
        sender.workspace_id,
        sender.run_id,
    ) != (command.actor_id, command.workspace_id, command.run_id):
        raise ExecutionDeniedError("Mixed notification sender command differs")
    credential = await services.reads.identities.current(expected_binding=sender)
    if not isinstance(credential, AuthenticatedWorkerIdentity):
        raise ExecutionDeniedError("Notification sealed credential unavailable")
    services.require_enabled()
    services.reads.require_registration(snapshot)
    services.reads.registrations.require_current(snapshot)
    return NotificationOperationGuard(credential, snapshot, services.reads.registrations)


async def prepare_notification_context(
    services: NotificationDispatchWorkerServices,
    command: SegmentCommand,
    *,
    workflow_id: str,
) -> NotificationContext:
    """Release an acquired lease when construction or cancellation prevents returning context."""
    services.require_enabled()
    if services.reads.facts.catalog.cycle_admission is not None:
        guard = await _mixed_operation_guard(services, command, workflow_id)
        snapshot, credential = guard.snapshot, guard.witness
        actual = await read_notification_dispatch(
            services, command, workflow_id, operation_guard=guard
        )
    else:
        actual = await read_notification_dispatch(services, command, workflow_id)
        snapshot = services.reads.registrations.snapshot()
        services.reads.require_registration(snapshot)
        credential = await services.reads.identities.current(expected_binding=actual.binding)
        if not isinstance(credential, AuthenticatedWorkerIdentity):
            raise ExecutionDeniedError("Notification sealed credential unavailable")
        guard = NotificationOperationGuard(credential, snapshot, services.reads.registrations)
    services.reads.require_registration(snapshot)
    guard.reader.require_current(snapshot)
    if actual.binding != snapshot.value.registration.sender:
        raise ExecutionDeniedError("Notification configured sender metadata changed")
    identity, scope = credential.identity, ledger_scope(actual.binding)
    command.require_scope(scope)
    lease = await recover_notification_lease(services, scope, credential, guard, command)
    try:
        await require_current_credential(services, scope, credential, guard)
        services.require_enabled()
        services.reads.require_registration(snapshot)
        if guard.reader is not services.reads.registrations:
            raise ExecutionDeniedError("Notification original registration reader changed")
        guard.reader.require_current(snapshot)
        if (
            lease.actor_id,
            lease.workspace_id,
            lease.task_id,
            lease.trace_id,
            lease.run_id,
            lease.segment_id,
        ) != (
            command.actor_id,
            command.workspace_id,
            command.task_id,
            command.trace_id,
            command.run_id,
            command.segment_id,
        ):
            raise ExecutionDeniedError("Notification acquired lease differs from permanent command")
        return NotificationContext(
            command,
            actual.binding,
            actual.action,
            actual.draft_id,
            identity,
            credential,
            guard,
            lease,
        )
    except BaseException:
        await services.execution.release(lease, identity)
        raise
