"""Fresh Brain scope checks share the company mutex and never mint work allowance."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import (
    AccessDeniedError,
    Capability,
    PrincipalAccess,
    VerifiedIdentity,
    WorkAccess,
    bind_work_scope,
    require_capability,
)
from nexus.company.brain.base import BrainReadScope
from nexus.company.directory_models import (
    DirectoryCompany,
    DirectoryMembership,
    RegisteredWork,
    WorkPrincipal,
)
from nexus.company.directory_store import _lineage_active
from nexus.harness.journal_models import CompanyControl

logger = structlog.get_logger()


class BrainDeniedError(AccessDeniedError):
    """Generic current Brain denial without revealing a foreign or restricted record."""


class BrainConflictError(ValueError):
    """An authorized known revision changed and requires explicit refresh/reassembly."""


@asynccontextmanager
async def brain_transaction(
    factory: async_sessionmaker[AsyncSession],
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    *,
    owner: bool = False,
) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
    """Lock CompanyControl first; all materialization stays in this bounded transaction."""
    async with factory() as session, session.begin():
        for key, value in (
            ("nexus.company_id", scope.company_id),
            ("nexus.workspace_id", scope.workspace_id),
            ("nexus.principal_id", scope.principal_id),
        ):
            await session.execute(select(func.set_config(key, str(value), True)))
        await session.execute(select(func.set_config("statement_timeout", "2000", True)))
        if await session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ):
            raise BrainDeniedError("Brain application connections cannot bypass row security")
        control = await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == scope.company_id)
            .with_for_update()
        )
        if control is None:
            raise BrainDeniedError("Current Brain scope is unavailable")
        access = await require_brain_scope(session, control, scope, identity, owner=owner)
        await _registered_binding(session, scope, access)
        now: datetime | None = await session.scalar(select(func.clock_timestamp()))
        if now is None or now.utcoffset() is None:
            raise BrainDeniedError("Current Brain clock is unavailable")
        try:
            yield session, control, now
        except Exception as exc:
            logger.warning(
                "brain_operation_rejected",
                company_id=str(scope.company_id),
                operation_id=str(scope.operation_id),
                task_id=str(scope.task_id) if scope.task_id else None,
                trace_id=str(scope.trace_id),
                error_type=type(exc).__name__,
            )
            raise


async def require_brain_scope(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    *,
    owner: bool = False,
) -> PrincipalAccess:
    """Reusable same-session boundary for context claim/publication, with no I/O outside DB."""
    company = await session.get(DirectoryCompany, scope.company_id)
    member = await session.get(DirectoryMembership, (scope.company_id, scope.principal_id))
    if (
        (scope.principal_id, scope.workspace_id) != (identity.principal_id, identity.workspace_id)
        or company is None
        or member is None
        or company.workspace_id != scope.workspace_id
        or company.owner_id != control.owner_id
    ):
        raise BrainDeniedError("Current Brain scope is unavailable")
    access = PrincipalAccess.model_validate(
        {
            "company_id": company.company_id,
            "workspace_id": company.workspace_id,
            "principal_id": member.principal_id,
            "owner_id": company.owner_id,
            "membership_role": member.role,
            "company_active": company.company_active,
            "workspace_active": company.workspace_active,
            "principal_active": member.principal_active,
            "membership_active": member.membership_active,
        }
    )
    try:
        require_capability(access, Capability.GRANT if owner else Capability.READ)
    except AccessDeniedError as exc:
        raise BrainDeniedError("Current Brain scope is unavailable") from exc
    return access


async def _registered_binding(
    session: AsyncSession, scope: BrainReadScope, access: PrincipalAccess
) -> None:
    if scope.task_id is None:
        return
    row = await session.get(RegisteredWork, (scope.company_id, scope.task_id))
    if row is None or row.actor_id != scope.actor_id or row.trace_id != scope.task_trace_id:
        raise BrainDeniedError("Registered Brain work binding is unavailable")
    allowed = await session.scalars(
        select(WorkPrincipal.principal_id).where(
            WorkPrincipal.company_id == scope.company_id, WorkPrincipal.task_id == scope.task_id
        )
    )
    work = WorkAccess(
        company_id=row.company_id,
        workspace_id=row.workspace_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        actor_id=row.actor_id,
        active=await _lineage_active(session, row),
        allowed_principals=tuple(allowed.all()),
    )
    try:
        bind_work_scope(
            access, work, task_id=row.task_id, trace_id=row.trace_id, capability=Capability.READ
        )
    except AccessDeniedError as exc:
        raise BrainDeniedError("Registered Brain work binding is unavailable") from exc


async def revalidate_brain_scope(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
) -> None:
    """Caller holds CompanyControl; claim/publication cannot reuse an old directory snapshot."""
    access = await require_brain_scope(session, control, scope, identity)
    await _registered_binding(session, scope, access)
