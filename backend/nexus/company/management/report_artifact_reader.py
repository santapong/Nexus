"""Production bounded report reader composition retains actual signed scope in every delegate."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True, slots=True)
class ReportArtifactReader:
    retriever: PersistentBrainRetriever
    artifacts: BoundedArtifactReader

    async def bounded_artifact(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        artifact_revision_id: UUID,
        *,
        start_byte: int,
        max_bytes: int,
        include_history: bool,
    ) -> ArtifactSlice:
        return await self.artifacts.bounded_artifact(
            scope,
            identity,
            artifact_revision_id,
            start_byte=start_byte,
            max_bytes=max_bytes,
            include_history=include_history,
        )

    async def citation_handles(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        ids: tuple[UUID, ...],
        *,
        include_history: bool,
    ) -> tuple[CitationHandle, ...]:
        return await self.retriever.citation_handles(
            scope, identity, ids, include_history=include_history
        )

    async def revalidate_artifact_reference(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        reference: ArtifactRevisionRef,
        now: datetime,
    ) -> None:
        await self.artifacts.revalidate_artifact_reference(
            session, control, scope, identity, reference, now
        )
