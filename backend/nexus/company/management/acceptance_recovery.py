"""Reconcile proof of an already succeeded native check, without another effect or publication."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_evidence import (
    PreparedReportCheck,
    ProtectedReportEvidenceResolver,
)
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import (
    acceptance_record,
    build_acceptance,
    write_acceptance,
)
from nexus.company.management.acceptance_recovery_target import (
    recovery_target,
    require_recovered_payload,
)
from nexus.company.management.acceptance_store import require_final_time
from nexus.company.management.acceptance_support import acceptance_scope
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class AcceptanceRecovery:
    """Configured protected reader and native resolver; no caller result, permit or verdict."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        resolver: ProtectedReportEvidenceResolver,
        producer: NativeReportProducer,
    ) -> None:
        self.factory, self.resolver, self.producer = factory, resolver, producer

    async def reconcile_verified_result(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        check_action_id: UUID,
    ) -> WorkAcceptance:
        """Finish current proof only for the exact original already-succeeded native check."""
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            target, reference = await recovery_target(
                session, control, lease, check_action_id, await db_now(session)
            )
        scope = acceptance_scope(lease, target.action_id)
        prepared = await self.resolver.prepare(scope, identity, target, reference)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            require_acceptance(
                await recovery_target(
                    session, control, lease, check_action_id, await db_now(session)
                )
                == (target, reference)
            )
            await self.resolver.revalidate(
                session, control, scope, identity, prepared, await db_now(session)
            )
            await require_recovered_payload(
                session,
                scope,
                check_action_id,
                prepared,
                await self.producer.check_payload(session, scope, prepared.command),
            )
            result = await save_recovered_proof(session, lease, scope, prepared)
            require_acceptance(
                await recovery_target(
                    session, control, lease, check_action_id, await db_now(session)
                )
                == (target, reference)
            )
            work = await execution_row(session, lease_scope(lease))
            final = await db_now(session)
            require_lease(work, lease, final)
            require_final_time(prepared, final)
            return result


async def save_recovered_proof(
    session: AsyncSession,
    lease: ExecutionLease,
    scope: BrainReadScope,
    prepared: PreparedReportCheck,
) -> WorkAcceptance:
    """Append immutable proof under the current reconciliation fence; no M1 facts change."""
    work = await execution_row(session, lease_scope(lease))
    now = await db_now(session)
    require_lease(work, lease, now)
    require_acceptance(lease.mode == "reconcile")
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
        return old
    await write_acceptance(session, record)
    artifact = await session.get(
        BrainArtifactRevision, (lease.company_id, prepared.protected.artifact.artifact_revision_id)
    )
    require_acceptance(artifact is not None)
    assert artifact is not None
    await append_event(
        session,
        scope,
        kind="verification_recorded",
        resource_id=artifact.resource_id,
        action_id=prepared.command.target.action_id,
        deduplication_key=f"management.acceptance:{record.acceptance_id}",
        now=now,
    )
    require_lease(work, lease, await db_now(session))
    require_final_time(prepared, await db_now(session))
    return record
