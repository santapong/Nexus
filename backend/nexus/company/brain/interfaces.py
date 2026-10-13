"""Trusted async service boundaries; IDs/DTOs do not replace current locked authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import (
    AssembledContext,
    ContextAuthorityState,
    ContextManifest,
    ContextSelection,
)
from nexus.company.brain.retrieval import (
    CitationHandle,
    MaterializedEvidence,
    RetrievalResult,
    SearchRequest,
)
from nexus.company.brain.sources import IngestCommand, IngestReceipt
from nexus.company.contracts.actions import ResourceRevision
from nexus.harness.journal_models import CompanyControl


class BrainIngestor(Protocol):
    async def ingest(
        self, scope: BrainReadScope, identity: VerifiedIdentity, command: IngestCommand
    ) -> IngestReceipt:
        """Use registered symbol/blob policy and current owner scope; no paid extraction default."""
        ...


class BrainRetriever(Protocol):
    async def search(
        self, scope: BrainReadScope, identity: VerifiedIdentity, request: SearchRequest
    ) -> RetrievalResult:
        """Apply current ACL before rank, limits, counts and opaque handle publication."""
        ...

    async def materialize(
        self, scope: BrainReadScope, identity: VerifiedIdentity, handles: tuple[CitationHandle, ...]
    ) -> tuple[MaterializedEvidence, ...]:
        """Recheck all source/derivation contributors in a short company-first transaction."""
        ...


class ContextAuthorityProvider(Protocol):
    async def current(
        self, session: AsyncSession, scope: BrainReadScope, identity: VerifiedIdentity
    ) -> ContextAuthorityState:
        """Root-owned fast current policy/state; fixture projections never back production."""
        ...


class ContextAssembler(Protocol):
    async def assemble(
        self, scope: BrainReadScope, identity: VerifiedIdentity, selection: ContextSelection
    ) -> AssembledContext:
        """Use mandatory server ContextLimits and authority provider; no model calls."""
        ...


class ContextRevalidator(Protocol):
    async def revalidate_context(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        manifest: ContextManifest,
        now: datetime,
    ) -> tuple[ResourceRevision, ...]:
        """Use existing locked transaction; no nested transaction/commit/provider I/O."""
        ...
