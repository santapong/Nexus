"""Test-only actual protected source/output and native current ledger/registration lookup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.check_contracts import (
    CitationCheckSource,
    ReportCheckInput,
    ReportCheckSnapshot,
)
from nexus.company.management.plans import PlanPayload
from nexus.company.management.report_rules import (
    project_report,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.management_acceptance_report_fixture import report_facts
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


class FixtureActualInputLoader:
    """Configured fixture lookup re-derives actual DB facts; no caller snapshot/auth flag."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        reader: PersistentBrainRetriever,
        source: ArtifactSlice,
        handles: tuple[CitationHandle, ...],
        observed: datetime,
        payload: PlanPayload,
    ) -> None:
        self.factory, self.reader, self.source, self.handles, self.observed = (
            factory,
            reader,
            source,
            handles,
            observed,
        )
        self.payload = payload
        self.output: ArtifactSlice | None = None
        self.after_load: Callable[[], Awaitable[None]] | None = None

    async def load(
        self, scope: BrainReadScope, identity: VerifiedIdentity, target: VerificationSpec
    ) -> ReportCheckInput:
        source = await self.reader.bounded_artifact(
            scope,
            identity,
            self.source.artifact.artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )
        output = await self.reader.bounded_artifact(
            scope,
            identity,
            target.artifacts[0].artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )
        assert not source.has_more and not output.has_more
        self.source, self.output = source, output
        ids = tuple(row.evidence_id for row in self.handles)
        self.handles = await self.reader.citation_handles(
            scope, identity, ids, include_history=False
        )
        async with brain_transaction(self.factory, scope, identity) as (session, control, _):
            result = await self._command(session, control, scope, identity, target)
        if self.after_load:
            await self.after_load()
        return result

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: ReportCheckInput,
        now: datetime,
    ) -> ReportCheckInput:
        assert self.output is not None
        await self.reader.revalidate_handles(session, control, scope, identity, self.handles, now)
        await self.reader.revalidate_artifact(session, control, scope, identity, self.source, now)
        await self.reader.revalidate_artifact(session, control, scope, identity, self.output, now)
        return await self._command(session, control, scope, identity, command.target)

    async def _command(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        target: VerificationSpec,
    ) -> ReportCheckInput:
        assert self.output is not None
        row = await session.get(ExecutionWork, (scope.company_id, target.author.task_id))
        assert row is not None
        operating = project_report(
            await report_facts(
                session, control, scope, identity, self.source, self.observed, self.payload
            )
        )
        citations = tuple(
            CitationCheckSource(
                evidence=handle.record,
                head=next(
                    head
                    for head in self.source.source_heads
                    if head.source_id == handle.record.source.source_id
                ),
                raw_text=self.source.text,
            )
            for handle in self.handles
        )
        return ReportCheckInput(
            company_id=scope.company_id,
            target=target,
            output=self.output.artifact,
            output_utf8=self.output.text.encode(),
            snapshot=ReportCheckSnapshot(
                company_id=scope.company_id,
                observed_at=self.observed,
                author_binding=target.author,
                author_registration=snapshot(row).registration,
                author_registration_sha256=row.registration_hash,
                operating=operating,
                citations=citations,
            ),
        )


async def input_source(
    factory: async_sessionmaker[AsyncSession], reader: PersistentBrainRetriever
) -> tuple[ArtifactSlice, tuple[CitationHandle, ...], datetime]:
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, observed):
        ids = tuple(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id).where(BrainEvidence.company_id == COMPANY)
                )
            ).all()
        )
    handles = await reader.citation_handles(
        owner_scope(), identity(OWNER), ids, include_history=False
    )
    source = await reader.bounded_artifact(
        owner_scope(),
        identity(OWNER),
        handles[0].record.artifact.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    return source, handles, observed
