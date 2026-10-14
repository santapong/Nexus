"""Signed current owner cancellation is immutable administrative intent, never a worker attempt."""

from __future__ import annotations

from uuid import uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cancellation_contracts import CancellationCommand, OwnerCancellation
from nexus.company.management.cancellation_models import WorkCancellation
from nexus.company.management.cancellation_support import actual_binding, cancellation_record
from nexus.company.management.control_support import ManagementConflictError, db_clock
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.runtime_models import ExecutionWork


class WorkCancellationStore:
    """Leave issued facts and ledgers intact; descendants inherit the permanent stop.

    Cancelling a procedure permanently stops that goal. Restart requires a new
    owner intent for a new goal; historical daily/lifetime charges remain.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    # Keep this >50-line owner transaction together: exact target/replay and
    # immutable insert must share current signed scope and the company mutex.
    async def cancel(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        command: CancellationCommand,
    ) -> OwnerCancellation:
        """Cancel native work, replay the exact operation or record a distinct owner instruction."""
        command = CancellationCommand.model_validate_json(command.model_dump_json(by_alias=True))
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            target = command.target
            work = await session.get(ExecutionWork, (scope.company_id, target.task_id))
            registered = await session.get(RegisteredWork, (scope.company_id, target.task_id))
            if (
                command.company_id != scope.company_id
                or work is None
                or registered is None
                or actual_binding(work) != target
                or (registered.workspace_id, registered.actor_id, registered.trace_id)
                != (target.workspace_id, target.actor_id, target.trace_id)
            ):
                raise ManagementDeniedError("Exact cancellation target is unavailable")
            old = await session.scalar(
                select(WorkCancellation).where(
                    WorkCancellation.company_id == scope.company_id,
                    WorkCancellation.operation_id == scope.operation_id,
                )
            )
            if old is not None:
                record = cancellation_record(old)
                if (
                    record.target,
                    record.registration_sha256,
                    record.reason,
                    record.owner_id,
                    record.audit_trace_id,
                ) != (
                    target,
                    work.registration_hash,
                    command.reason,
                    control.owner_id,
                    scope.trace_id,
                ):
                    raise ManagementConflictError(
                        "Cancellation operation cannot bind another owner intent"
                    )
                return record
            now = await db_clock(session)
            record = OwnerCancellation(
                company_id=scope.company_id,
                cancellation_id=uuid5(scope.company_id, f"work-cancellation:{scope.operation_id}"),
                target=target,
                registration_sha256=work.registration_hash,
                reason=command.reason,
                owner_id=control.owner_id,
                operation_id=scope.operation_id,
                audit_trace_id=scope.trace_id,
                recorded_at=now,
            )
            session.add(
                WorkCancellation(
                    company_id=record.company_id,
                    cancellation_id=record.cancellation_id,
                    operation_id=record.operation_id,
                    task_id=target.task_id,
                    trace_id=target.trace_id,
                    run_id=target.run_id,
                    binding_json=target.model_dump_json(by_alias=True),
                    registration_sha256=record.registration_sha256,
                    reason=record.reason,
                    owner_id=record.owner_id,
                    audit_trace_id=record.audit_trace_id,
                    recorded_at=record.recorded_at,
                )
            )
            await session.flush()
            return record
