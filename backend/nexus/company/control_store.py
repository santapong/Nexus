"""Owner controls that do not require or create registered work/cost allowance."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import structlog
from pydantic import StrictBool, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import (
    Capability,
    CompanyControlScope,
    PrincipalAccess,
    VerifiedIdentity,
    require_capability,
)
from nexus.company.contracts.base import Contract
from nexus.company.directory_contracts import MembershipRole
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership
from nexus.harness.journal_models import CompanyControl

logger = structlog.get_logger()
_PAUSED = TypeAdapter(StrictBool)


class CompanyPauseState(Contract):
    """Persisted pause and the control audit identity; no work/cost grant is present."""

    owner_id: UUID
    operation_id: UUID
    trace_id: UUID
    paused: StrictBool


async def _require_owner(
    session: AsyncSession, scope: CompanyControlScope, identity: VerifiedIdentity
) -> CompanyControl:
    control = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == scope.company_id)
        .with_for_update()
    )
    if control is None or (control.owner_id, scope.principal_id) != (
        scope.principal_id,
        identity.principal_id,
    ):
        raise ValueError("Only the actual verified owner controls company pause")
    company = await session.get(DirectoryCompany, scope.company_id)
    member = await session.get(DirectoryMembership, (scope.company_id, scope.principal_id))
    if (
        company is None
        or member is None
        or company.owner_id != control.owner_id
        or company.workspace_id != identity.workspace_id
    ):
        raise ValueError("Current company/workspace/owner mapping is unavailable")
    require_capability(
        PrincipalAccess(
            company_id=scope.company_id,
            workspace_id=company.workspace_id,
            principal_id=scope.principal_id,
            owner_id=control.owner_id,
            membership_role=cast(MembershipRole, member.role),
            company_active=company.company_active,
            workspace_active=company.workspace_active,
            principal_active=member.principal_active,
            membership_active=member.membership_active,
        ),
        Capability.PAUSE,
    )
    return control


class CompanyControls:
    """Use fresh owner checks under the company lock before changing durable pause."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def set_paused_registered(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, paused: StrictBool
    ) -> CompanyPauseState:
        """Persist pause before any work exists; earlier gateway membership is insufficient.

        The caller derives this control scope from verified authentication. The
        operation/trace identity is logged and returned; a durable control-event
        ledger is a separate integration gate. Existing issued effects still need
        reconciliation. This operation neither creates work nor releases cost holds.
        """
        paused = _PAUSED.validate_python(paused)
        async with self._factory() as session, session.begin():
            for key, value in (
                ("nexus.company_id", scope.company_id),
                ("nexus.workspace_id", identity.workspace_id),
                ("nexus.principal_id", identity.principal_id),
            ):
                await session.execute(select(func.set_config(key, str(value), True)))
            control = await _require_owner(session, scope, identity)
            control.paused = paused
            await session.flush()
            state = CompanyPauseState(
                company_id=scope.company_id,
                owner_id=control.owner_id,
                operation_id=scope.operation_id,
                trace_id=scope.trace_id,
                paused=paused,
            )

        logger.info(
            "company_pause_changed",
            company_id=str(scope.company_id),
            task_id=str(scope.operation_id),
            operation_id=str(scope.operation_id),
            trace_id=str(scope.trace_id),
            principal_id=str(scope.principal_id),
            paused=paused,
        )
        return state
