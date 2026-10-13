"""Owner-issued standing capabilities under the shared company transaction lock.

The grant authorizes a reviewed offline internal adapter, not an arbitrary
tool name. The caller's journal owns action single use, costs and counters.
Current bindings are owner declarations; persisted M3 plans/charters remain
a later proof. The additive profile migration supplies RLS/immutability guards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import (
    Capability,
    CompanyControlScope,
    PrincipalAccess,
    VerifiedIdentity,
    require_capability,
)
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.directory_models import DirectoryCompany, DirectoryMembership, RegisteredWork
from nexus.company.directory_store import _active
from nexus.harness.approvals import ApprovalContext
from nexus.harness.journal_budget import _require_member, require_registered_access
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl
from nexus.harness.standing_contracts import (
    StandingDeniedError,
    StandingGrant,
    StandingRecord,
    WorkAuthority,
    canonical_grant,
    grant_hash,
    require_binding_update,
    require_eligible_permissions,
    require_standing_policy,
)
from nexus.harness.standing_models import StandingAuthorityGrant, StandingWorkAuthority

logger = structlog.get_logger()


def _record(row: StandingAuthorityGrant) -> StandingRecord:
    grant = StandingGrant.model_validate_json(row.snapshot_json)
    if grant_hash(grant) != row.snapshot_hash or (
        grant.company_id,
        grant.task_id,
        grant.actor_id,
        grant.grant_id,
    ) != (row.company_id, row.task_id, row.actor_id, row.grant_id):
        raise StandingDeniedError("Persisted standing snapshot binding disagrees")
    return StandingRecord(
        company_id=row.company_id,
        grant=grant,
        grant_hash=row.snapshot_hash,
        active=row.active,
        revoked_at=row.revoked_at,
    )


def _binding(row: StandingWorkAuthority) -> WorkAuthority:
    return WorkAuthority(
        company_id=row.company_id,
        task_id=row.task_id,
        plan_id=row.plan_id,
        plan_revision=row.plan_revision,
        charter_id=row.charter_id,
        charter_revision=row.charter_revision,
    )


async def _locked_control(session: AsyncSession, company_id: UUID) -> CompanyControl:
    control = await session.scalar(
        select(CompanyControl).where(CompanyControl.company_id == company_id).with_for_update()
    )
    if control is None:
        raise StandingDeniedError("Company is unavailable")
    return control


async def _require_owner(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
) -> None:
    if (control.company_id, control.owner_id) != (scope.company_id, scope.principal_id) or (
        identity.principal_id != scope.principal_id
    ):
        raise StandingDeniedError("Standing authority requires the actual verified owner")
    company = await session.get(DirectoryCompany, scope.company_id)
    member = await session.get(DirectoryMembership, (scope.company_id, scope.principal_id))
    if (
        company is None
        or member is None
        or (company.owner_id, company.workspace_id) != (control.owner_id, identity.workspace_id)
    ):
        raise StandingDeniedError("Current company/workspace owner binding is unavailable")
    require_capability(
        PrincipalAccess.model_validate(
            {
                "company_id": company.company_id,
                "workspace_id": company.workspace_id,
                "principal_id": member.principal_id,
                "owner_id": control.owner_id,
                "membership_role": member.role,
                "company_active": company.company_active,
                "workspace_active": company.workspace_active,
                "principal_active": member.principal_active,
                "membership_active": member.membership_active,
            }
        ),
        Capability.GRANT,
    )


async def _registered_actor(
    session: AsyncSession, company_id: UUID, task_id: UUID
) -> RegisteredWork:
    row = await session.get(RegisteredWork, (company_id, task_id))
    if row is None or not await _active(session, row):
        raise StandingDeniedError("Registered work or current ancestry is inactive")
    member = await session.get(DirectoryMembership, (company_id, row.actor_id))
    company = await session.get(DirectoryCompany, company_id)
    if member is None or company is None:
        raise StandingDeniedError("Registered actor cannot perform internal work")
    _require_member(company, member, row.actor_id, Capability.INTERNAL_PROPOSAL)
    return row


async def require_standing_authority(
    session: AsyncSession,
    control: CompanyControl,
    action: ActionProposal,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    grant_id: UUID,
    now: datetime,
    resources: tuple[ResourceRevision, ...],
) -> StandingGrant:
    """Recheck current grant inside the caller's effect transaction and FIRST control lock.

    Never consume authorization, reserve a budget, refund costs or reset counters
    here. The journal must bind/consume the exact action and reserve cost once.
    """
    if control.company_id != scope.company_id:
        raise StandingDeniedError("Control and action scope disagree")
    await require_registered_access(session, control, action, scope, identity, owner=False)
    row = await session.scalar(
        select(StandingAuthorityGrant).where(
            StandingAuthorityGrant.company_id == scope.company_id,
            StandingAuthorityGrant.grant_id == grant_id,
        )
    )
    if row is None or not row.active or row.revoked_at is not None:
        raise StandingDeniedError("Standing grant is missing or revoked")
    record = _record(row)
    bound = await session.get(StandingWorkAuthority, (scope.company_id, scope.task_id))
    if bound is None:
        raise StandingDeniedError("Current owner-declared work authority is absent")
    context = ApprovalContext(
        company_id=scope.company_id,
        owner_id=control.owner_id,
        actor_id=scope.principal_id,
        now=now,
        policy_version=control.policy_version,
        price_version=control.price_version,
        paused=control.paused,
        resources=resources,
    )
    require_standing_policy(record.grant, action, context, _binding(bound))
    return record.grant


class StandingAuthorityStore:
    """Persist explicit owner capabilities; no implicit owner or generic-internal approval."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    @asynccontextmanager
    async def _session(
        self, scope: CompanyControlScope, identity: VerifiedIdentity
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl]]:
        async with self._factory() as session, session.begin():
            for key, value in (
                ("nexus.company_id", scope.company_id),
                ("nexus.workspace_id", identity.workspace_id),
                ("nexus.principal_id", identity.principal_id),
            ):
                await session.execute(select(func.set_config(key, str(value), True)))
            try:
                control = await _locked_control(session, scope.company_id)
                await _require_owner(session, control, scope, identity)
                yield session, control
            except Exception as exc:
                logger.warning(
                    "standing_authority_rejected",
                    company_id=str(scope.company_id),
                    task_id=str(scope.operation_id),
                    trace_id=str(scope.trace_id),
                    error_type=type(exc).__name__,
                )
                raise

    async def bind_work(
        self, binding: WorkAuthority, scope: CompanyControlScope, identity: VerifiedIdentity
    ) -> WorkAuthority:
        """Register or monotonically revise owner-declared plan/charter references."""
        binding = WorkAuthority.model_validate(binding.model_dump())
        if binding.company_id != scope.company_id:
            raise StandingDeniedError("Work authority belongs to another company")
        async with self._session(scope, identity) as (session, control):
            if control.paused:
                raise StandingDeniedError("Paused company cannot add or revise standing authority")
            await _registered_actor(session, binding.company_id, binding.task_id)
            row = await session.get(StandingWorkAuthority, (binding.company_id, binding.task_id))
            if row is None:
                row = StandingWorkAuthority(**binding.model_dump(exclude={"schema_version"}))
                session.add(row)
            else:
                require_binding_update(_binding(row), binding)
                for name in ("plan_id", "plan_revision", "charter_id", "charter_revision"):
                    setattr(row, name, getattr(binding, name))
            await session.flush()
            return _binding(row)

    async def issue(
        self,
        grant: StandingGrant,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        now: datetime,
    ) -> StandingRecord:
        """Persist a server-created immutable owner snapshot; replay never renews it."""
        snapshot = canonical_grant(grant)
        grant = StandingGrant.model_validate_json(snapshot)
        require_eligible_permissions(grant)
        if (grant.company_id, grant.owner_id) != (scope.company_id, scope.principal_id):
            raise StandingDeniedError("Standing grant requires its actual owner scope")
        async with self._session(scope, identity) as (session, control):
            existing = await session.get(StandingAuthorityGrant, grant.grant_id)
            if existing is not None:
                if existing.snapshot_json != snapshot:
                    raise StandingDeniedError("Grant ID already binds another immutable snapshot")
                return _record(existing)
            work = await _registered_actor(session, scope.company_id, grant.task_id)
            binding = await session.get(StandingWorkAuthority, (scope.company_id, grant.task_id))
            await self._require_new_grant(grant, control, work, binding, now)
            row = StandingAuthorityGrant(
                grant_id=grant.grant_id,
                company_id=grant.company_id,
                task_id=grant.task_id,
                actor_id=grant.actor_id,
                snapshot_json=snapshot,
                snapshot_hash=grant_hash(grant),
                active=True,
                revoked_at=None,
            )
            session.add(row)
            await session.flush()
            return _record(row)

    @staticmethod
    async def _require_new_grant(
        grant: StandingGrant,
        control: CompanyControl,
        work: RegisteredWork,
        binding: StandingWorkAuthority | None,
        now: datetime,
    ) -> None:
        if now.utcoffset() is None or not grant.issued_at <= now < grant.expires_at:
            raise StandingDeniedError("Standing grant is not currently valid")
        if (
            control.paused
            or (grant.policy_version, grant.price_version)
            != (control.policy_version, control.price_version)
            or grant.actor_id != work.actor_id
            or grant.max_action_cost_usd > control.work_cap_usd
        ):
            raise StandingDeniedError("Current actor, company policy or cost cap disagrees")
        expected = WorkAuthority.model_validate(
            {name: getattr(grant, name) for name in WorkAuthority.model_fields}
        )
        if binding is None or _binding(binding) != expected:
            raise StandingDeniedError("Grant does not bind the current declared plan and charter")

    async def revoke(
        self, grant_id: UUID, scope: CompanyControlScope, identity: VerifiedIdentity, now: datetime
    ) -> StandingRecord:
        """Irreversibly revoke under current owner authority, including while paused."""
        if now.utcoffset() is None:
            raise StandingDeniedError("Revocation time must be timezone-aware")
        async with self._session(scope, identity) as (session, _control):
            row = await session.scalar(
                select(StandingAuthorityGrant).where(
                    StandingAuthorityGrant.company_id == scope.company_id,
                    StandingAuthorityGrant.grant_id == grant_id,
                )
            )
            if row is None:
                raise StandingDeniedError("Standing grant is unavailable")
            if row.active:
                row.active, row.revoked_at = False, now
                await session.flush()
            return _record(row)
