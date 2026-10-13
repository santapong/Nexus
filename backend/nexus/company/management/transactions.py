"""Owner management reuses fresh company identity/mutex checks and grants no source access."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import BrainDeniedError, brain_transaction
from nexus.harness.journal_models import CompanyControl


class ManagementDeniedError(BrainDeniedError):
    """Current management owner/control scope is unavailable; no foreign state is exposed."""


@asynccontextmanager
async def management_owner_transaction(
    factory: async_sessionmaker[AsyncSession],
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    *,
    allow_paused: bool = False,
) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
    """Share CompanyControl first and current signed mapping, without creating work.

    Only explicit owner control maintenance may enter while paused. Ordinary
    management admission and all execution keep their independent current gates.
    Blob/model/network work belongs outside this short database transaction.
    """
    if type(allow_paused) is not bool:
        raise ManagementDeniedError("Management control maintenance flag is invalid")
    current = BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    async with brain_transaction(factory, current, identity, owner=True) as (
        session,
        control,
        now,
    ):
        if control.paused and not allow_paused:
            raise ManagementDeniedError("Company management intake is paused")
        yield session, control, now
