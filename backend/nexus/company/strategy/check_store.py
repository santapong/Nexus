"""Two-phase protected SV check publication; no effect, receipt or work acceptance is created."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_input_support import artifact_input_closure
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact
from nexus.company.strategy.artifact_identity import strategy_reference
from nexus.company.strategy.check_actor import revalidate_strategy_check_actor_locked
from nexus.company.strategy.check_rows import (
    require_strategy_check_replay_locked,
    write_strategy_check_locked,
)
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import strategy_publication_scope
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class StrategyCheckStore:
    """Concrete native wiring; caller-created prepared values grant no authority."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: BrainBlobStore,
        reader: StrategyInputReader,
    ) -> None:
        if reader.artifacts.factory is not factory or reader.artifacts.blobs is not blobs:
            raise ValueError("Strategy check store requires its actual native factory/storage")
        self.factory, self.blobs, self.reader = factory, blobs, reader

    async def _replay(
        self,
        session: AsyncSession,
        lease: ExecutionLease,
        action_id: UUID,
        prepared: PreparedStrategyArtifact,
    ) -> None:
        scope = strategy_publication_scope(lease, action_id)
        ref = strategy_reference(prepared, action_id)
        await require_strategy_check_replay_locked(
            session, scope, action_id, prepared, self.reader.rules.check, self.blobs.storage_symbol
        )
        closure = await artifact_input_closure(session, scope, (ref.artifact_revision_id,))
        expected = {row.artifact_revision_id for row in prepared.inputs.artifacts} | {
            ref.artifact_revision_id
        }
        require_acceptance(set(closure.artifact_revision_ids) == expected and len(expected) <= 33)

    async def publish_check(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        prepared: PreparedStrategyArtifact,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> ArtifactRevisionRef:
        """Publish only one already-issued C; preserve initial/current windows through commit."""
        # This >50-line two-phase boundary retains both audiences through every awaited write.
        prepared = PreparedStrategyArtifact.model_validate(prepared.model_dump(warnings=False))
        ref = strategy_reference(prepared, action_id)
        scope = strategy_publication_scope(lease, action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            initial = await revalidate_strategy_check_actor_locked(
                self.reader,
                session,
                control,
                lease,
                identity,
                action_id,
                prepared,
                credential=credential,
            )
            existing = await session.get(
                BrainArtifactRevision, (lease.company_id, ref.artifact_revision_id)
            )
            if existing is not None:
                await self._replay(session, lease, action_id, prepared)
                work = await execution_row(session, lease_scope(lease))
                now = await db_now(session)
                require_lease(work, lease, now, execute=True)
                initial.protection.require_time(now)
                return ref
        await self.blobs.save(ref, prepared.raw_bytes)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            current = await revalidate_strategy_check_actor_locked(
                self.reader,
                session,
                control,
                lease,
                identity,
                action_id,
                prepared,
                credential=credential,
            )
            existing = await session.get(
                BrainArtifactRevision, (lease.company_id, ref.artifact_revision_id)
            )
            if existing is None:
                await write_strategy_check_locked(
                    session,
                    scope,
                    action_id,
                    prepared,
                    self.reader.rules.check,
                    self.reader.rules.check_policy,
                    self.blobs.storage_symbol,
                    await db_now(session),
                )
            await self._replay(session, lease, action_id, prepared)
            await session.flush()
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now, execute=True)
            initial.protection.require_time(now)
            current.protection.require_time(now)
            return ref
