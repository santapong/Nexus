"""Fresh company directory reads and owner-controlled registration transactions.

No legacy JWT role or arbitrary audit ID can create membership/work allowance.
The profile migration supplies RLS and immutable-identity guards; mounting this
store behind authenticated HTTP remains a separate integration gate.

This store exceeds the usual file limit because one scoped work package owns
the shared tenant transaction/lock boundary and its read/registration methods.
Contracts and metadata are separate; helpers keep individual operations bounded.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import cast
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, PrincipalAccess, VerifiedIdentity, WorkAccess
from nexus.company.directory_contracts import (
    CompanyRegistration,
    DirectoryDeniedError,
    MembershipChange,
    MembershipRole,
    WorkAllocation,
    WorkRegistration,
    validate_registration,
)
from nexus.company.directory_models import (
    DirectoryCompany,
    DirectoryMembership,
    RegisteredWork,
    WorkPrincipal,
)
from nexus.harness.journal_models import CompanyControl, WorkBudget

logger = structlog.get_logger()
_MAX_LINEAGE = 16


async def _work(session: AsyncSession, company_id: UUID, task_id: UUID) -> RegisteredWork | None:
    row = await session.scalar(
        select(RegisteredWork).where(
            RegisteredWork.company_id == company_id,
            RegisteredWork.task_id == task_id,
        )
    )
    return row


async def _lineage_active(session: AsyncSession, row: RegisteredWork) -> bool:
    seen: set[UUID] = set()
    for _ in range(_MAX_LINEAGE):
        if not row.active or row.task_id in seen:
            return False
        seen.add(row.task_id)
        if row.parent_task_id is None:
            return row.root_task_id == row.task_id
        parent = await _work(session, row.company_id, row.parent_task_id)
        if parent is None or (parent.root_task_id, parent.workspace_id) != (
            row.root_task_id,
            row.workspace_id,
        ):
            return False
        row = parent
    return False


async def _allocation(session: AsyncSession, row: RegisteredWork) -> WorkAllocation:
    budget = await session.scalar(
        select(WorkBudget).where(
            WorkBudget.company_id == row.company_id,
            WorkBudget.task_id == row.task_id,
        )
    )
    return WorkAllocation(
        company_id=row.company_id,
        workspace_id=row.workspace_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        actor_id=row.actor_id,
        parent_task_id=row.parent_task_id,
        root_task_id=row.root_task_id,
        allocation_usd=row.allocation_usd,
        delegated_usd=row.delegated_usd,
        spent_usd=budget.spent_usd if budget else Decimal(0),
        held_usd=budget.held_usd if budget else Decimal(0),
        active=await _active(session, row),
    )


async def _grants(session: AsyncSession, row: RegisteredWork, *, current: bool) -> tuple[UUID, ...]:
    statement = select(WorkPrincipal.principal_id).where(
        WorkPrincipal.company_id == row.company_id,
        WorkPrincipal.task_id == row.task_id,
    )
    if current:
        statement = statement.join(
            DirectoryMembership,
            (DirectoryMembership.company_id == WorkPrincipal.company_id)
            & (DirectoryMembership.principal_id == WorkPrincipal.principal_id),
        ).where(
            DirectoryMembership.principal_active.is_(True),
            DirectoryMembership.membership_active.is_(True),
        )
    return tuple(sorted((await session.scalars(statement)).all(), key=str))


async def _members_active(session: AsyncSession, registration: WorkRegistration) -> bool:
    members = (
        await session.scalars(
            select(DirectoryMembership).where(
                DirectoryMembership.company_id == registration.company_id,
                DirectoryMembership.principal_id.in_(registration.allowed_principals),
            )
        )
    ).all()
    return len(members) == len(registration.allowed_principals) and all(
        row.principal_active
        and row.membership_active
        and (row.principal_id != registration.actor_id or row.role != "viewer")
        for row in members
    )


async def _active(session: AsyncSession, row: RegisteredWork) -> bool:
    company = await session.get(DirectoryCompany, row.company_id)
    grants = await _grants(session, row, current=True)
    return bool(
        company
        and company.company_active
        and company.workspace_active
        and row.actor_id in grants
        and await _lineage_active(session, row)
    )


def _new_row(request: WorkRegistration, root: UUID) -> RegisteredWork:
    return RegisteredWork(
        company_id=request.company_id,
        task_id=request.task_id,
        workspace_id=request.workspace_id,
        trace_id=request.trace_id,
        actor_id=request.actor_id,
        parent_task_id=request.parent_task_id,
        root_task_id=root,
        allocation_usd=request.allocation_usd,
        delegated_usd=Decimal(0),
        active=True,
    )


async def _register_new(
    session: AsyncSession,
    request: WorkRegistration,
    scope: CompanyControlScope,
    control: CompanyControl,
) -> WorkAllocation:
    if not await _members_active(session, request):
        raise DirectoryDeniedError(
            "every grant needs active membership and actor cannot be a viewer"
        )
    parent_row = (
        await _work(session, scope.company_id, request.parent_task_id)
        if request.parent_task_id
        else None
    )
    parent = await _allocation(session, parent_row) if parent_row is not None else None
    root = validate_registration(
        request, scope, owner_id=control.owner_id, work_cap_usd=control.work_cap_usd, parent=parent
    )
    row = _new_row(request, root)
    session.add(row)
    if parent_row is not None:
        parent_row.delegated_usd += request.allocation_usd
    await session.flush()
    session.add_all(
        [
            WorkPrincipal(company_id=scope.company_id, task_id=row.task_id, principal_id=p)
            for p in request.allowed_principals
        ]
    )
    await session.flush()
    result = await _allocation(session, row)
    if not result.active:
        raise DirectoryDeniedError("new work exceeds the active bounded parent lineage")
    return result


class PersistentCompanyDirectory:
    """Use transaction-local tenant/identity contexts, without any elevated fallback."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    @asynccontextmanager
    async def _session(
        self,
        company_id: UUID | None,
        principal_id: UUID,
        *,
        workspace_id: UUID | None,
        task_id: UUID,
        trace_id: UUID,
    ) -> AsyncIterator[AsyncSession]:
        async with self._factory() as session, session.begin():
            for key, value in (
                ("nexus.company_id", company_id),
                ("nexus.workspace_id", workspace_id),
                ("nexus.principal_id", principal_id),
            ):
                await session.execute(
                    select(func.set_config(key, str(value) if value else "", True))
                )
            try:
                yield session
            except Exception as exc:
                logger.warning(
                    "company_directory_rejected",
                    company_id=str(company_id),
                    task_id=str(task_id),
                    trace_id=str(trace_id),
                    error_type=type(exc).__name__,
                )
                raise

    async def _owner(
        self, session: AsyncSession, scope: CompanyControlScope, *, bootstrap: bool = False
    ) -> tuple[CompanyControl, DirectoryCompany | None]:
        control = await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == scope.company_id)
            .with_for_update()
        )
        if control is None or control.owner_id != scope.principal_id:
            raise DirectoryDeniedError("only the actual company owner controls its directory")
        company = await session.get(DirectoryCompany, scope.company_id)
        if bootstrap and company is None:
            return control, None
        member = await session.get(DirectoryMembership, (scope.company_id, scope.principal_id))
        if (
            company is None
            or company.owner_id != control.owner_id
            or not company.company_active
            or not company.workspace_active
            or member is None
            or not member.principal_active
            or not member.membership_active
            or member.role != "owner"
        ):
            raise DirectoryDeniedError(
                "current directory owner membership is inactive or inconsistent"
            )
        return control, company

    async def bootstrap(
        self, registration: CompanyRegistration, scope: CompanyControlScope
    ) -> None:
        """Trusted operator bootstrap after CompanyControl creation; no HTTP self-registration."""
        registration = CompanyRegistration.model_validate(registration.model_dump())
        if (registration.company_id, registration.owner_id) != (
            scope.company_id,
            scope.principal_id,
        ):
            raise DirectoryDeniedError("bootstrap owner and company must match operator scope")
        async with self._session(
            scope.company_id,
            scope.principal_id,
            workspace_id=registration.workspace_id,
            task_id=scope.operation_id,
            trace_id=scope.trace_id,
        ) as session:
            control, existing = await self._owner(session, scope, bootstrap=True)
            if existing is not None:
                if (existing.workspace_id, existing.owner_id) != (
                    registration.workspace_id,
                    registration.owner_id,
                ):
                    raise DirectoryDeniedError("company already has a different directory binding")
                return
            session.add(
                DirectoryCompany(
                    company_id=scope.company_id,
                    workspace_id=registration.workspace_id,
                    owner_id=control.owner_id,
                    company_active=True,
                    workspace_active=True,
                )
            )
            await session.flush()
            session.add(
                DirectoryMembership(
                    company_id=scope.company_id,
                    principal_id=control.owner_id,
                    role="owner",
                    principal_active=True,
                    membership_active=True,
                )
            )

    async def set_membership(self, change: MembershipChange, scope: CompanyControlScope) -> None:
        """Change current scoped membership only under the persisted actual owner."""
        change = MembershipChange.model_validate(change.model_dump())
        if change.company_id != scope.company_id:
            raise DirectoryDeniedError("membership command belongs to another company")
        async with self._session(
            scope.company_id,
            scope.principal_id,
            workspace_id=None,
            task_id=scope.operation_id,
            trace_id=scope.trace_id,
        ) as session:
            control, _ = await self._owner(session, scope)
            if (change.role == "owner") != (change.principal_id == control.owner_id):
                raise DirectoryDeniedError("membership role cannot replace the actual owner")
            member = await session.get(DirectoryMembership, (scope.company_id, change.principal_id))
            if member is None:
                member = DirectoryMembership(
                    company_id=scope.company_id, principal_id=change.principal_id
                )
                session.add(member)
            member.role, member.principal_active = change.role, change.principal_active
            member.membership_active = change.membership_active

    async def lookup_principal(
        self, identity: VerifiedIdentity, *, task_id: UUID, trace_id: UUID
    ) -> PrincipalAccess | None:
        """Discover only the verified workspace/current member, then bind company context."""
        async with self._session(
            None,
            identity.principal_id,
            workspace_id=identity.workspace_id,
            task_id=task_id,
            trace_id=trace_id,
        ) as session:
            result = (
                await session.execute(
                    select(DirectoryCompany, DirectoryMembership)
                    .join(
                        DirectoryMembership,
                        DirectoryMembership.company_id == DirectoryCompany.company_id,
                    )
                    .where(
                        DirectoryCompany.workspace_id == identity.workspace_id,
                        DirectoryMembership.principal_id == identity.principal_id,
                    )
                )
            ).one_or_none()
            if result is None:
                return None
            company, member = result
            await session.execute(
                select(func.set_config("nexus.company_id", str(company.company_id), True))
            )
            control = await session.get(CompanyControl, company.company_id)
            if control is None or control.owner_id != company.owner_id:
                return None
            return PrincipalAccess(
                company_id=company.company_id,
                workspace_id=company.workspace_id,
                principal_id=member.principal_id,
                owner_id=control.owner_id,
                membership_role=cast(MembershipRole, member.role),
                company_active=company.company_active,
                workspace_active=company.workspace_active,
                principal_active=member.principal_active,
                membership_active=member.membership_active,
            )

    async def lookup_work(
        self, company_id: UUID, task_id: UUID, *, trace_id: UUID
    ) -> WorkAccess | None:
        """Return current registered identity and active grants; absence creates nothing."""
        async with self._session(
            company_id, UUID(int=0), workspace_id=None, task_id=task_id, trace_id=trace_id
        ) as session:
            row = await _work(session, company_id, task_id)
            if row is None or row.trace_id != trace_id:
                return None
            company = await session.get(DirectoryCompany, company_id)
            grants = await _grants(session, row, current=True)
            active = bool(
                company
                and company.company_active
                and company.workspace_active
                and row.actor_id in grants
                and await _lineage_active(session, row)
            )
            return WorkAccess(
                company_id=company_id,
                workspace_id=row.workspace_id,
                task_id=row.task_id,
                trace_id=row.trace_id,
                actor_id=row.actor_id,
                active=active,
                allowed_principals=grants,
            )

    async def allocation(
        self, company_id: UUID, task_id: UUID, *, trace_id: UUID
    ) -> WorkAllocation | None:
        """Read an existing lifetime allocation; this cannot initialize a cost ledger."""
        async with self._session(
            company_id, UUID(int=0), workspace_id=None, task_id=task_id, trace_id=trace_id
        ) as session:
            row = await _work(session, company_id, task_id)
            return (
                await _allocation(session, row)
                if row is not None and row.trace_id == trace_id
                else None
            )

    async def register_work(
        self, registration: WorkRegistration, scope: CompanyControlScope
    ) -> WorkAllocation:
        """Partition a parent once under the company lock; retries preserve the exact identity."""
        registration = WorkRegistration.model_validate(registration.model_dump())
        if (
            registration.company_id != scope.company_id
            or registration.task_id == scope.operation_id
        ):
            raise DirectoryDeniedError("registration company/audit identity is invalid")
        async with self._session(
            scope.company_id,
            scope.principal_id,
            workspace_id=registration.workspace_id,
            task_id=registration.task_id,
            trace_id=registration.trace_id,
        ) as session:
            control, company = await self._owner(session, scope)
            if (
                control.paused
                or company is None
                or company.workspace_id != registration.workspace_id
            ):
                raise DirectoryDeniedError(
                    "company intake is paused or workspace binding disagrees"
                )
            existing = await _work(session, scope.company_id, registration.task_id)
            if existing is not None:
                await self._require_same_registration(session, registration, existing)
                return await _allocation(session, existing)
            return await _register_new(session, registration, scope, control)

    async def _require_same_registration(
        self, session: AsyncSession, request: WorkRegistration, existing: RegisteredWork
    ) -> None:
        if (
            existing.workspace_id,
            existing.trace_id,
            existing.actor_id,
            existing.parent_task_id,
            existing.allocation_usd,
            await _grants(session, existing, current=False),
        ) != (
            request.workspace_id,
            request.trace_id,
            request.actor_id,
            request.parent_task_id,
            request.allocation_usd,
            tuple(sorted(request.allowed_principals, key=str)),
        ):
            raise DirectoryDeniedError("immutable registered work identity or quota conflicts")

    async def set_work_active(
        self, scope: CompanyControlScope, *, task_id: UUID, active: bool
    ) -> None:
        """Pause/cancel existing work under owner scope without refunding delegated slices."""
        if type(active) is not bool:
            raise DirectoryDeniedError("work activity must be an explicit boolean")
        async with self._session(
            scope.company_id,
            scope.principal_id,
            workspace_id=None,
            task_id=task_id,
            trace_id=scope.trace_id,
        ) as session:
            await self._owner(session, scope)
            row = await _work(session, scope.company_id, task_id)
            if row is None:
                raise DirectoryDeniedError("registered work is unavailable")
            row.active = active
