"""Fresh native owner pause/current membership gate; leases alone are not worker drain evidence."""

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.transactions import management_owner_transaction
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now

if TYPE_CHECKING:
    from nexus.operations.backup_postgres import PostgresBackupAdapter


async def require_capture_owner(
    factory: async_sessionmaker[AsyncSession],
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    adapter: "PostgresBackupAdapter",
) -> None:
    async with management_owner_transaction(factory, scope, identity, allow_paused=True) as (
        session,
        control,
        _,
    ):
        await adapter.require_owner_binding(session)
        if not control.paused:
            raise ValueError("Backup requires current native owner pause")
        live = await session.scalar(
            select(func.count())
            .select_from(ExecutionWork)
            .where(
                ExecutionWork.company_id == scope.company_id,
                ExecutionWork.lease_until > await db_now(session),
            )
        )
        if live:
            raise ValueError("Backup requires quiescent native leases")
