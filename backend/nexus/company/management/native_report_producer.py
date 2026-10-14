"""Read-only server-native preparation; actual publication remains separately governed."""

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import acceptance_scope, resolve_target
from nexus.company.management.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import (
    REPORT_CHECK_RECIPE,
    CitationCheckSource,
    ReportCheckInput,
    ReportCheckSnapshot,
    SourceQuoteClaim,
    StructuredInternalReport,
)
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactInputs,
    GeneratedArtifactPayload,
)
from nexus.company.management.native_report_inputs import native_manifest
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import OperatingReportStore, stored_report
from nexus.company.management.operation_models import ManagementReportSnapshot
from nexus.company.management.report_checker import check_internal_report
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.report_renderer import render_native_report
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now, lease_scope, runtime_transaction
from nexus.harness.journal_models import CompanyControl

REPORT_RENDER_RECIPE = "native-report-render-v1"


class NativeReportProducer:
    """Prepare exact native reports/checks without issuing actions or impersonating the owner."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        reports: OperatingReportStore,
        inputs: PersistentReportInputLoader,
    ) -> None:
        self.factory, self.reports, self.inputs = factory, reports, inputs

    async def prepare_report(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        report_id: UUID,
        evidence_ids: tuple[UUID, ...],
    ) -> GeneratedArtifactPayload:
        """Read protected source blobs before entering the actual author transaction."""
        sources = await self.inputs.prepare_sources(scope, identity, evidence_ids)
        async with brain_transaction(self.factory, scope, identity) as (session, control, _):
            await self.inputs.revalidate_sources(
                session, control, scope, identity, sources, await db_now(session)
            )
            record, references = await self.reports.prepare_author_inputs(
                session, control, scope, identity, report_id
            )
            return await self.report_payload(session, scope, record, sources, references)

    async def recompute_report(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        raw: bytes,
    ) -> GeneratedArtifactPayload:
        """Resolve selectors from bytes, then independently render actual current saved facts."""
        require_acceptance(0 < len(raw) <= 262144)
        declared = StructuredInternalReport.model_validate_json(raw)
        require_acceptance(declared.company_id == scope.company_id)
        ids = tuple(row.evidence_id for row in declared.claims if isinstance(row, SourceQuoteClaim))
        sources = await self.inputs.resolve_sources(session, control, scope, identity, ids)
        record, references = await self.reports.prepare_author_inputs(
            session,
            control,
            scope,
            identity,
            declared.operating.snapshot.report_id,
        )
        payload = await self.report_payload(session, scope, record, sources, references)
        require_acceptance(payload.raw_bytes == raw)
        return payload

    async def report_payload(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        record: SavedOperatingReport,
        sources: tuple[CitationCheckSource, ...],
        references: tuple[ArtifactRevisionRef, ...],
    ) -> GeneratedArtifactPayload:
        """Build exact bytes and complete persisted input identity from server-resolved facts."""
        require_acceptance(
            all(
                row.evidence.ingested_at <= record.observed_at
                and row.head.observed_at <= record.observed_at
                for row in sources
            )
        )
        report = render_native_report(record.projection, sources, observed_at=record.observed_at)
        manifest, classification = await native_manifest(
            session,
            scope,
            (*references, *(row.evidence.artifact for row in sources)),
            tuple(head.current for head in record.data.source_heads),
            tuple(
                EvidenceRef(company_id=scope.company_id, evidence_id=row.evidence.evidence_id)
                for row in sources
            ),
            record.data.required_resource_ids,
        )
        raw = report.model_dump_json().encode()
        return GeneratedArtifactPayload(
            company_id=scope.company_id,
            raw_bytes=raw,
            output_sha256=hashlib.sha256(raw).hexdigest(),
            input_snapshot_sha256=canonical_sha256(
                ReportProductionSnapshot(saved=record, citations=sources, manifest=manifest)
            ),
            recipe_version=REPORT_RENDER_RECIPE,
            data_classification=classification,
            inputs=manifest,
        )

    async def prepare_check(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        author_action_id: UUID,
    ) -> GeneratedArtifactPayload:
        """Use an actual successful author receipt and distinct current protected verifier."""
        scope = acceptance_scope(lease, author_action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            target = await resolve_target(
                session, control, lease, author_action_id, await db_now(session)
            )
        command = await self.inputs.load(scope, identity, target)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            require_acceptance(
                await resolve_target(
                    session, control, lease, author_action_id, await db_now(session)
                )
                == target
            )
            current = await self.inputs.revalidate(
                session, control, scope, identity, command, await db_now(session)
            )
            require_acceptance(current == command)
            return await self.check_payload(session, scope, command)

    async def check_payload(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        command: ReportCheckInput,
    ) -> GeneratedArtifactPayload:
        """Render mechanical checks including inconclusive/reject without publishing acceptance."""
        snapshot = command.snapshot
        require_acceptance(snapshot is not None and snapshot.operating is not None)
        assert snapshot is not None and snapshot.operating is not None
        native = await session.get(
            ManagementReportSnapshot,
            (scope.company_id, snapshot.operating.snapshot.report_id),
        )
        require_acceptance(native is not None)
        assert native is not None
        saved = stored_report(native)
        result = check_internal_report(command)
        manifest, classification = await native_manifest(
            session,
            scope,
            (command.output, *(row.evidence.artifact for row in snapshot.citations)),
            tuple(head.current for head in saved.data.source_heads),
            tuple(
                EvidenceRef(company_id=scope.company_id, evidence_id=row.evidence.evidence_id)
                for row in snapshot.citations
            ),
            saved.data.required_resource_ids,
        )
        raw = result.model_dump_json().encode()
        return GeneratedArtifactPayload(
            company_id=scope.company_id,
            raw_bytes=raw,
            output_sha256=hashlib.sha256(raw).hexdigest(),
            input_snapshot_sha256=canonical_sha256(
                CheckProductionSnapshot(
                    target=command.target,
                    snapshot=snapshot,
                    output_sha256=command.output.sha256,
                    manifest=manifest,
                )
            ),
            recipe_version=REPORT_CHECK_RECIPE,
            data_classification=classification,
            inputs=manifest,
        )


class ReportProductionSnapshot(ValueContract):
    """Full resolved facts sealed into an exact input identity, never a permission."""

    saved: SavedOperatingReport
    citations: tuple[CitationCheckSource, ...]
    manifest: GeneratedArtifactInputs


class CheckProductionSnapshot(ValueContract):
    """Full native check identity binds protected output hash and all input facts."""

    target: VerificationSpec
    snapshot: ReportCheckSnapshot
    output_sha256: str
    manifest: GeneratedArtifactInputs
