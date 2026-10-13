"""Current-owner transaction and recording-fence validation without actor impersonation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership, RegisteredWork
from nexus.execution.owner_reconcile_contracts import OwnerReconciliationLease
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import execution_row, snapshot
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl

logger = structlog.get_logger()


@asynccontextmanager
async def owner_transaction(
    factory: async_sessionmaker[AsyncSession],
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    task_id: UUID,
) -> AsyncIterator[tuple[AsyncSession, ExecutionWork]]:
    """Use current actual owner scope even when original actor/work has been revoked."""
    async with factory() as session, session.begin():
        for key, value in (
            ("nexus.company_id", scope.company_id),
            ("nexus.workspace_id", identity.workspace_id),
            ("nexus.principal_id", identity.principal_id),
        ):
            await session.execute(select(func.set_config(key, str(value), True)))
        try:
            control = await session.scalar(
                select(CompanyControl)
                .where(CompanyControl.company_id == scope.company_id)
                .with_for_update()
            )
            company = await session.get(DirectoryCompany, scope.company_id)
            member = await session.get(
                DirectoryMembership, (scope.company_id, identity.principal_id)
            )
            if (
                control is None
                or company is None
                or member is None
                or (
                    scope.principal_id != identity.principal_id
                    or scope.principal_id != control.owner_id
                    or company.owner_id != control.owner_id
                    or company.workspace_id != identity.workspace_id
                    or member.role != "owner"
                    or not member.principal_active
                    or not member.membership_active
                    or not company.company_active
                    or not company.workspace_active
                    or scope.operation_id == task_id
                )
            ):
                raise ExecutionDeniedError(
                    "Current true-owner reconciliation identity is unavailable"
                )
            row = await execution_row(
                session,
                LedgerScope(
                    company_id=scope.company_id,
                    task_id=task_id,
                    trace_id=scope.trace_id,
                    principal_id=scope.principal_id,
                ),
            )
            registered = await session.get(RegisteredWork, (scope.company_id, task_id))
            if (
                registered is None
                or (
                    registered.company_id,
                    registered.task_id,
                    registered.trace_id,
                    registered.actor_id,
                    registered.workspace_id,
                )
                != (
                    row.company_id,
                    row.task_id,
                    row.trace_id,
                    row.actor_id,
                    row.workspace_id,
                )
                or row.workspace_id != identity.workspace_id
            ):
                raise ExecutionDeniedError("Original actor/work/run binding disagrees")
            snapshot(row)
            yield session, row
        except Exception as exc:
            logger.warning(
                "owner_reconciliation_rejected",
                task_id=str(task_id),
                trace_id=str(scope.trace_id),
                operation_id=str(scope.operation_id),
                principal_id=str(scope.principal_id),
                error_type=type(exc).__name__,
            )
            raise


def require_owner_lease(row: ExecutionWork, owned: OwnerReconciliationLease, now: datetime) -> None:
    """Owner fencing validates recorder identity without changing original actor fields."""
    lease, scope = owned.execution, owned.control_scope
    if (
        (
            row.company_id,
            row.task_id,
            row.trace_id,
            row.actor_id,
            row.workspace_id,
            row.run_id,
            row.workflow_version,
            row.segment_id,
            row.worker_id,
            row.fence,
            row.lease_mode,
            row.lease_principal_id,
        )
        != (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.actor_id,
            lease.workspace_id,
            lease.run_id,
            lease.workflow_version,
            lease.segment_id,
            lease.worker_id,
            lease.fence,
            "reconcile",
            scope.principal_id,
        )
        or row.lease_until is None
        or row.lease_until <= now
    ):
        raise ExecutionDeniedError(
            "Owner reconciliation lease is stale, expired or differently owned"
        )
