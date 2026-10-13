"""Persistent independent acceptance of protected mechanical evidence, never M1 completion."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import (
    AcceptanceInvalidation,
    WorkAcceptance,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_evidence import (
    PreparedReportCheck,
    ProtectedReportEvidenceResolver,
)
from nexus.company.management.acceptance_freshness import require_qualified_time
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import (
    acceptance_record,
    build_acceptance,
    write_acceptance,
)
from nexus.company.management.acceptance_support import acceptance_scope, resolve_target
from nexus.company.management.transactions import management_owner_transaction
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)

InvalidationReason = Literal[
    "source_changed", "criteria_changed", "proof_unavailable", "scope_revoked", "invalid_check"
]


def require_final_time(prepared: PreparedReportCheck, now: datetime) -> None:
    require_acceptance(
        all(
            row.expires_at is None or row.expires_at > now
            for artifact in (prepared.protected, *prepared.input_artifacts)
            for row in artifact.contributors
        )
    )
    require_qualified_time(prepared.freshness, now)
    snapshot = prepared.command.snapshot
    if snapshot:
        require_acceptance(
            all(
                row.head.fresh_until is None
                or row.head.fresh_until > now
                or row.head.fresh_until <= snapshot.observed_at
                for row in snapshot.citations
            )
        )


async def publish_locked(
    session: AsyncSession,
    lease: ExecutionLease,
    scope: BrainReadScope,
    prepared: PreparedReportCheck,
) -> WorkAcceptance:
    work = await execution_row(session, lease_scope(lease))
    now = await db_now(session)
    require_lease(work, lease, now, execute=True)
    require_final_time(prepared, now)
    record = build_acceptance(prepared, now)
    previous = await session.get(ManagementWorkAcceptance, (lease.company_id, record.acceptance_id))
    if previous is not None:
        old = acceptance_record(previous)
        require_acceptance(
            old.target == record.target
            and old.proofs == record.proofs
            and old.verdict == record.verdict
            and old.limitations == record.limitations
        )
        now = await db_now(session)
        require_lease(work, lease, now, execute=True)
        require_final_time(prepared, now)
        return old
    await write_acceptance(session, record)
    result_row = await session.get(
        BrainArtifactRevision, (lease.company_id, prepared.protected.artifact.artifact_revision_id)
    )
    require_acceptance(result_row is not None)
    assert result_row is not None
    await append_event(
        session,
        scope,
        kind="verification_recorded",
        resource_id=result_row.resource_id,
        action_id=prepared.command.target.action_id,
        deduplication_key=f"management.acceptance:{record.acceptance_id}",
        now=now,
    )
    now = await db_now(session)
    require_lease(work, lease, now, execute=True)
    require_final_time(prepared, now)
    return record


class WorkAcceptanceStore:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], resolver: ProtectedReportEvidenceResolver
    ) -> None:
        self._factory, self._resolver = factory, resolver

    async def publish_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        action_id: UUID,
        protected_result: ArtifactRevisionRef,
    ) -> WorkAcceptance:
        lease = ExecutionLease.model_validate_json(lease.model_dump_json())
        async with runtime_transaction(self._factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            target = await resolve_target(session, control, lease, action_id, await db_now(session))
        scope = acceptance_scope(lease, action_id)
        prepared = await self._resolver.prepare(scope, identity, target, protected_result)
        async with runtime_transaction(self._factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            current = await resolve_target(
                session, control, lease, action_id, await db_now(session)
            )
            require_acceptance(current == target)
            await self._resolver.revalidate(
                session, control, scope, identity, prepared, await db_now(session)
            )
            return await publish_locked(session, lease, scope, prepared)

    async def invalidate(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        acceptance_id: UUID,
        reason: InvalidationReason,
    ) -> AcceptanceInvalidation:
        async with management_owner_transaction(
            self._factory, scope, identity, allow_paused=True
        ) as (session, _, _):
            row = await session.get(ManagementWorkAcceptance, (scope.company_id, acceptance_id))
            require_acceptance(row is not None)
            assert row is not None
            record = acceptance_record(row)
            invalidation_id = uuid5(acceptance_id, f"invalidation:{reason}:{row.target_sha256}")
            previous = await session.get(
                ManagementAcceptanceInvalidation, (scope.company_id, invalidation_id)
            )
            if previous:
                return _invalidation(previous)
            result = AcceptanceInvalidation(
                company_id=scope.company_id,
                invalidation_id=invalidation_id,
                acceptance_id=acceptance_id,
                target_sha256=row.target_sha256,
                reason=reason,
                recorded_by=identity.principal_id,
                recorded_at=await db_now(session),
            )
            session.add(
                ManagementAcceptanceInvalidation(**result.model_dump(exclude={"schema_version"}))
            )
            await session.flush()
            await invalidation_event(session, scope, identity, record, result)
            return result


async def invalidation_event(
    session: AsyncSession,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    record: WorkAcceptance,
    result: AcceptanceInvalidation,
) -> None:
    artifact = await session.get(
        BrainArtifactRevision,
        (scope.company_id, record.proofs[0].result_artifact.artifact_revision_id),
    )
    require_acceptance(artifact is not None)
    assert artifact is not None
    event_scope = acceptance_scope_from_owner(scope, identity)
    await append_event(
        session,
        event_scope,
        kind="verification_recorded",
        resource_id=artifact.resource_id,
        action_id=record.target.action_id,
        deduplication_key=f"management.invalidation:{result.invalidation_id}",
        now=result.recorded_at,
    )


def acceptance_scope_from_owner(
    scope: CompanyControlScope, identity: VerifiedIdentity
) -> BrainReadScope:
    return BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=identity.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )


def _invalidation(row: ManagementAcceptanceInvalidation) -> AcceptanceInvalidation:
    return AcceptanceInvalidation.model_validate(
        {
            name: getattr(row, name)
            for name in AcceptanceInvalidation.model_fields
            if name != "schema_version"
        }
    )
