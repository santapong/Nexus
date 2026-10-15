"""Two-phase native B+Brief publication from one actual issued S intent; no new effect."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_input_support import artifact_input_closure
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_contracts import (
    PreparedStrategyPublication,
    StrategyPublishedArtifacts,
)
from nexus.company.strategy.publication_protection import strategy_publication_scope
from nexus.company.strategy.publication_rows import (
    require_strategy_publication_replay_locked,
    write_strategy_publication_locked,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class StrategyBundleStore:
    """Concrete trusted reader/storage composition; no supplied authorization callback."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: BrainBlobStore,
        reader: StrategyInputReader,
    ) -> None:
        if reader.artifacts.factory is not factory or reader.artifacts.blobs is not blobs:
            raise ValueError(
                "Strategy publisher must share its actual protected reader factory/storage"
            )
        self.factory, self.blobs, self.reader = factory, blobs, reader

    async def _exists(self, session: AsyncSession, prepared: PreparedStrategyPublication) -> bool:
        ids = (
            prepared.compiled.original_bundle.artifact.artifact_revision_id,
            prepared.brief.artifact_revision_id,
        )
        values = []
        for key in ids:
            values.append(
                await session.scalar(
                    select(BrainArtifactRevision.artifact_revision_id).where(
                        BrainArtifactRevision.company_id == prepared.original.company_id,
                        BrainArtifactRevision.artifact_revision_id == key,
                    )
                )
            )
        bundle, brief = values
        require_acceptance((bundle is None) == (brief is None))
        return brief is not None

    async def _closure(
        self, session: AsyncSession, lease: ExecutionLease, prepared: PreparedStrategyPublication
    ) -> None:
        scope = strategy_publication_scope(lease, prepared.action_id)
        closure = await artifact_input_closure(
            session, scope, (prepared.brief.artifact_revision_id,)
        )
        expected = {row.artifact_revision_id for row in prepared.original.snapshot.inputs.artifacts}
        expected.update(
            (
                prepared.compiled.original_bundle.artifact.artifact_revision_id,
                prepared.brief.artifact_revision_id,
            )
        )
        require_acceptance(set(closure.artifact_revision_ids) == expected and len(expected) <= 32)

    async def publish_author(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        prepared: PreparedStrategyPublication,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategyPublishedArtifacts:
        """Publish/replay two immutable graphs; an artifact never substitutes for a receipt."""
        # This >50-line two-phase boundary keeps first/current audiences through final writes.
        prepared = PreparedStrategyPublication.model_validate(prepared.model_dump(warnings=False))
        require_acceptance(prepared.action_id == action_id)
        scope = strategy_publication_scope(lease, action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            await require_strategy_application_role(session)
            exists = await self._exists(session, prepared)
            initial = await self.reader.revalidate_author_locked(
                session, control, lease, identity, action_id, prepared, credential=credential
            )
            if exists:
                await require_strategy_publication_replay_locked(
                    session, scope, prepared, self.blobs.storage_symbol
                )
                await self._closure(session, lease, prepared)
                work = await execution_row(session, lease_scope(lease))
                now = await db_now(session)
                require_lease(work, lease, now, execute=True)
                initial.require_time(now)
                return self._published(prepared)
        await self.blobs.save(prepared.compiled.original_bundle.artifact, prepared.bundle_bytes)
        await self.blobs.save(prepared.brief, prepared.compiled.prepared.raw_bytes)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            await require_strategy_application_role(session)
            exists = await self._exists(session, prepared)
            current = await self.reader.revalidate_author_locked(
                session, control, lease, identity, action_id, prepared, credential=credential
            )
            if not exists:
                await write_strategy_publication_locked(
                    session,
                    scope,
                    prepared,
                    self.reader.rules.write,
                    self.reader.rules.bundle_policy,
                    self.reader.rules.brief_policy,
                    self.blobs.storage_symbol,
                    await db_now(session),
                )
            await require_strategy_publication_replay_locked(
                session, scope, prepared, self.blobs.storage_symbol
            )
            await self._closure(session, lease, prepared)
            await session.flush()
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now, execute=True)
            initial.require_time(now)
            current.require_time(now)
            return self._published(prepared)

    @staticmethod
    def _published(prepared: PreparedStrategyPublication) -> StrategyPublishedArtifacts:
        return StrategyPublishedArtifacts(
            company_id=prepared.original.company_id,
            bundle=prepared.compiled.original_bundle,
            brief=prepared.brief,
        )
