"""Test server renderer uses actual public saved-report and protected source revalidation."""

import hashlib
import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import EvidenceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CitationCheckSource
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactInputs,
    GeneratedArtifactPayload,
)
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.report_renderer import render_native_report
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import CompanyControl


def rendered_payload(
    saved: SavedOperatingReport, sources: tuple[CitationCheckSource, ...]
) -> GeneratedArtifactPayload:
    """Derive exact source quotes, native ledger/status facts and complete resources."""
    raw = (
        render_native_report(saved.projection, sources, observed_at=saved.observed_at)
        .model_dump_json(by_alias=True)
        .encode()
    )
    refs = {row.evidence.artifact.artifact_revision_id: row.evidence.artifact for row in sources}
    return GeneratedArtifactPayload(
        company_id=saved.company_id,
        raw_bytes=raw,
        output_sha256=hashlib.sha256(raw).hexdigest(),
        input_snapshot_sha256=canonical_sha256(saved),
        recipe_version="native-internal-report-v1",
        data_classification="internal",
        inputs=GeneratedArtifactInputs(
            company_id=saved.company_id,
            artifacts=tuple(refs[key] for key in sorted(refs)),
            contributors=tuple(head.current for head in saved.data.source_heads),
            evidence=tuple(
                EvidenceRef(company_id=saved.company_id, evidence_id=row.evidence.evidence_id)
                for row in sources
            ),
            required_resource_ids=saved.data.required_resource_ids,
        ),
    )


class NativeReportValidator:
    """Fixture-only actual native compiler; no supplied DTO echo/owner impersonation/pass SQL."""

    def __init__(
        self,
        reports: OperatingReportStore,
        loader: PersistentReportInputLoader,
        saved: SavedOperatingReport,
        sources: tuple[CitationCheckSource, ...],
    ) -> None:
        self.reports, self.loader, self.saved, self.sources = reports, loader, saved, sources
        self.calls = 0

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        lease: ExecutionLease,
        actual_action: ActionProposal,
        prepared: GeneratedArtifactPayload,
        now: datetime,
    ) -> None:
        self.calls += 1
        parameters = GeneratedArtifactActionParameters.model_validate_json(
            json.dumps(actual_action.parameters)
        )
        if parameters.report_id != self.saved.report_id or parameters.evidence_ids != tuple(
            source.evidence.evidence_id for source in self.sources
        ):
            raise ValueError("Actual native report selector differs")
        actual = await self.reports.prepare_author_output(
            session, control, scope, identity, self.saved.report_id
        )
        await self.loader.revalidate_sources(session, control, scope, identity, self.sources, now)
        if rendered_payload(actual, self.sources) != prepared:
            raise ValueError(
                "Native saved-report/source rendering differs from prepared bytes or inputs"
            )
