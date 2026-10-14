"""Production actual report inputs; no supplied verdict or impersonated owner scope."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.retrieval_records import bundles, heads
from nexus.company.brain.scope_support import brain_transaction, require_brain_scope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourcePolicies
from nexus.company.management.check_contracts import (
    CitationCheckSource,
    ReportCheckInput,
    ReportCheckSnapshot,
    StructuredInternalReport,
)
from nexus.company.management.report_input_contracts import (
    OperatingReportReader as OperatingReportReader,
)
from nexus.company.management.report_input_contracts import (
    ProtectedReportReader as ProtectedReportReader,
)
from nexus.company.management.report_input_contracts import (
    native_author as native_author,
)
from nexus.company.management.report_input_sources import (
    MAX_REPORT_BYTES,
    MAX_SOURCE_BYTES,
    protected_bytes,
    report_request,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class PersistentReportInputLoader:
    """Actual protected bytes outside locks; native registration/source/ledger reread inside."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        reader: ProtectedReportReader,
        reports: OperatingReportReader,
        *,
        source_policies: RegisteredSourcePolicies,
    ) -> None:
        self.factory, self.reader, self.reports = factory, reader, reports
        self.source_policies = source_policies

    async def load(
        self, scope: BrainReadScope, identity: VerifiedIdentity, target: VerificationSpec
    ) -> ReportCheckInput:
        require_acceptance(target.company_id == scope.company_id and len(target.artifacts) == 1)
        output = target.artifacts[0]
        raw = await protected_bytes(
            self.reader, scope, identity, output, max_bytes=MAX_REPORT_BYTES
        )
        report, ids = report_request(target, output, raw)
        handles = await self.reader.citation_handles(scope, identity, ids, include_history=False)
        require_acceptance(tuple(row.evidence_id for row in handles) == ids)
        prepared = await self._source_bytes(scope, identity, handles)
        async with brain_transaction(self.factory, scope, identity) as (session, control, _):
            sources = await self._sources(session, control, scope, identity, ids)
            require_acceptance(
                tuple(row.model_copy(update={"source_policy": None}) for row in sources) == prepared
            )
            await self.reader.revalidate_artifact_reference(
                session, control, scope, identity, output, await db_now(session)
            )
            return await self._command(
                session, control, scope, identity, target, output, raw, report, sources
            )

    async def prepare_sources(
        self, scope: BrainReadScope, identity: VerifiedIdentity, ids: tuple[UUID, ...]
    ) -> tuple[CitationCheckSource, ...]:
        """Resolve complete actual protected citation bytes for native report preparation."""
        require_acceptance(len(ids) <= 32 and len(set(ids)) == len(ids))
        handles = await self.reader.citation_handles(scope, identity, ids, include_history=False)
        require_acceptance(tuple(row.evidence_id for row in handles) == ids)
        prepared = await self._source_bytes(scope, identity, handles)
        async with brain_transaction(self.factory, scope, identity) as (session, control, _):
            current = await self._sources(session, control, scope, identity, ids)
            require_acceptance(
                tuple(row.model_copy(update={"source_policy": None}) for row in current) == prepared
            )
            return current

    async def revalidate_sources(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        sources: tuple[CitationCheckSource, ...],
        now: datetime,
    ) -> None:
        """DB-only exact fresh source reread; neither source text nor a permit is returned."""
        await require_brain_scope(session, control, scope, identity)
        ids = tuple(row.evidence.evidence_id for row in sources)
        require_acceptance(len(ids) <= 32 and len(set(ids)) == len(ids))
        require_acceptance(await self._sources(session, control, scope, identity, ids) == sources)

    async def resolve_sources(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        ids: tuple[UUID, ...],
    ) -> tuple[CitationCheckSource, ...]:
        """Resolve native citations inside the caller's current company transaction."""
        await require_brain_scope(session, control, scope, identity)
        require_acceptance(0 < len(ids) <= 32 and len(set(ids)) == len(ids))
        return await self._sources(session, control, scope, identity, ids)

    async def load_native(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        target: VerificationSpec,
    ) -> ReportCheckInput:
        """Recompute protected native check inputs without blob I/O under the lock."""
        await require_brain_scope(session, control, scope, identity)
        require_acceptance(target.company_id == scope.company_id and len(target.artifacts) == 1)
        output = target.artifacts[0]
        await self.reader.revalidate_artifact_reference(
            session, control, scope, identity, output, await db_now(session)
        )
        artifact = await session.get(
            BrainArtifactRevision, (scope.company_id, output.artifact_revision_id)
        )
        require_acceptance(artifact is not None)
        assert artifact is not None
        raw = artifact.raw_text.encode()
        report, ids = report_request(target, output, raw)
        sources = await self.resolve_sources(session, control, scope, identity, ids)
        return await self._command(
            session, control, scope, identity, target, output, raw, report, sources
        )

    async def _source_bytes(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        handles: tuple[CitationHandle, ...],
    ) -> tuple[CitationCheckSource, ...]:
        unique = {row.record.artifact.artifact_revision_id: row.record.artifact for row in handles}
        require_acceptance(sum(row.byte_length for row in unique.values()) <= MAX_SOURCE_BYTES)
        material = {
            key: await protected_bytes(
                self.reader, scope, identity, ref, max_bytes=MAX_SOURCE_BYTES
            )
            for key, ref in unique.items()
        }
        return tuple(
            CitationCheckSource(
                evidence=row.record,
                head=next(
                    head
                    for head in row.source_heads
                    if head.source_id == row.record.source.source_id
                ),
                raw_text=material[row.record.artifact.artifact_revision_id].decode("utf-8"),
            )
            for row in handles
        )

    async def _sources(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        ids: tuple[UUID, ...],
    ) -> tuple[CitationCheckSource, ...]:
        records = await bundles(session, scope, ids) if ids else {}
        require_acceptance(set(records) == set(ids))
        current = (
            {
                row.source_id: row
                for row in await heads(
                    session, scope, tuple(records[key].record().source for key in ids)
                )
            }
            if ids
            else {}
        )
        result: list[CitationCheckSource] = []
        for key in ids:
            bundle, record = records[key], records[key].record()
            await self.reader.revalidate_artifact_reference(
                session, control, scope, identity, record.artifact, await db_now(session)
            )
            policy = self.source_policies.policy(bundle.source.source_symbol)
            require_acceptance(
                policy.source_symbol == bundle.source.source_symbol
                and policy.authority_profile == bundle.source.authority_profile
                and policy.data_classification == bundle.source.data_classification
                and bundle.source.external_key in policy.allowed_external_keys
                and policy.media_type == bundle.artifact.media_type
            )
            result.append(
                CitationCheckSource(
                    evidence=record,
                    head=current[record.source.source_id],
                    source_policy=policy,
                    raw_text=bundle.artifact.raw_text,
                )
            )
        return tuple(result)

    async def _command(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        target: VerificationSpec,
        output: ArtifactRevisionRef,
        raw: bytes,
        report: StructuredInternalReport,
        sources: tuple[CitationCheckSource, ...],
    ) -> ReportCheckInput:
        row = await session.get(ExecutionWork, (scope.company_id, target.author.task_id))
        require_acceptance(row is not None)
        assert row is not None
        binding, registration = native_author(row)
        require_acceptance(
            binding == target.author and row.registration_hash == target.work_snapshot_sha256
        )
        operating = await self.reports.current_projection(
            session, control, scope, identity, report, output=output
        )
        snapshot = (
            ReportCheckSnapshot(
                company_id=scope.company_id,
                observed_at=operating.snapshot.ledger.observed_at,
                author_binding=binding,
                author_registration=registration,
                author_registration_sha256=row.registration_hash,
                operating=operating,
                citations=sources,
            )
            if operating is not None
            else None
        )
        return ReportCheckInput(
            company_id=scope.company_id,
            target=target,
            output=output,
            output_utf8=raw,
            snapshot=snapshot,
        )

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: ReportCheckInput,
        now: datetime,
    ) -> ReportCheckInput:
        await require_brain_scope(session, control, scope, identity)
        require_acceptance(
            command.company_id == scope.company_id and command.output_utf8 is not None
        )
        assert command.output_utf8 is not None
        report, ids = report_request(command.target, command.output, command.output_utf8)
        await self.reader.revalidate_artifact_reference(
            session, control, scope, identity, command.output, await db_now(session)
        )
        output = await session.get(
            BrainArtifactRevision, (scope.company_id, command.output.artifact_revision_id)
        )
        require_acceptance(output is not None and output.raw_text.encode() == command.output_utf8)
        sources = await self._sources(session, control, scope, identity, ids)
        return await self._command(
            session,
            control,
            scope,
            identity,
            command.target,
            command.output,
            command.output_utf8,
            report,
            sources,
        )
