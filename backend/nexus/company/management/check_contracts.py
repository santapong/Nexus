"""Bounded mechanical report-check inputs/results; none confer acceptance or authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRecord, SourceHead
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    SourceTime,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_rules import OperatingProjection
from nexus.execution.runtime_contracts import ExecutionRegistration

REPORT_CHECK_RECIPE = "internal-report-mechanical-v1"
REPORT_CHECK_CRITERIA = (
    "report.schema.v1",
    "report.citations.v1",
    "report.source-time.v1",
    "report.claim-basis.v1",
    "report.ledger.v1",
    "report.status.v1",
)
CheckVerdict = Literal["pass", "reject", "inconclusive"]


class CitationCheckSource(ValueContract):
    """Protected source bytes and current head, supplied by the authenticated server."""

    evidence: EvidenceRecord
    head: SourceHead
    source_policy: SourcePolicy | None = None
    raw_text: Annotated[str, StringConstraints(max_length=2_097_152)]


class ReportCheckSnapshot(ManagementContract):
    """Actual M1 author registration plus separately hashed server-read report inputs."""

    observed_at: AwareDatetime
    author_binding: RunBinding
    author_registration: ExecutionRegistration
    author_registration_sha256: SHA256
    operating: OperatingProjection | None = None
    citations: tuple[CitationCheckSource, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def scoped(self) -> Self:
        """Decoding scope consistency is separate from fresh protected reads."""
        require_company(
            self.company_id,
            self.author_binding,
            self.author_registration.work,
            self.operating.snapshot if self.operating else None,
        )
        for source in self.citations:
            require_company(self.company_id, source.evidence, source.head)
        return self


class SourceQuoteClaim(ValueContract):
    """A source-reported quotation, explicitly distinct from independent acceptance."""

    kind: Literal["source_quote"]
    evidence_id: UUID
    source_revision_id: UUID
    artifact_revision_id: UUID
    span_sha256: SHA256
    quote: Annotated[str, StringConstraints(min_length=1, max_length=16_384)]
    source_event: SourceTime
    source_state: Literal["current", "historical"]
    freshness: Literal["fresh", "stale", "unavailable"]


class AcceptedWorkClaim(ValueContract):
    """Only the exact server-projected independently accepted work identity."""

    kind: Literal["accepted_work"]
    task_id: UUID
    acceptance_id: UUID


class SemanticClaim(ValueContract):
    """Expressible for an honest inconclusive check; arbitrary semantics are unsupported."""

    kind: Literal["semantic"]
    text: Name


ReportClaim = Annotated[
    SourceQuoteClaim | AcceptedWorkClaim | SemanticClaim, Field(discriminator="kind")
]


class StructuredInternalReport(ValueContract):
    """The complete mechanical wire format; free commentary cannot silently pass."""

    schema_version: Literal["nexus.company.internal-report.v1"]
    company_id: UUID
    operating: OperatingProjection
    claims: tuple[ReportClaim, ...] = Field(min_length=1, max_length=100)


class ReportCheckInput(ManagementContract):
    """Read-only actual bytes and snapshots; callers cannot publish these results."""

    target: VerificationSpec
    output: ArtifactRevisionRef
    output_utf8: Annotated[bytes, Field(max_length=2_097_152)] | None
    snapshot: ReportCheckSnapshot | None

    @model_validator(mode="after")
    def scoped(self) -> Self:
        """Keep exact declared targets in one structural company scope."""
        require_company(self.company_id, self.target, self.output, self.snapshot)
        return self


class CriterionCheckResult(ValueContract):
    """Explicit result for one exact declared criterion, including unsupported criteria."""

    criterion_id: Name
    verdict: CheckVerdict
    reason: Symbol


class ReportCheckPayload(ManagementContract):
    """Hashable mechanical evidence only, with no trusted-publisher identity or permission."""

    recipe: Symbol
    target_sha256: SHA256
    output_sha256: SHA256 | None
    input_snapshot_sha256: SHA256 | None
    verdict: CheckVerdict
    criteria: tuple[CriterionCheckResult, ...] = Field(min_length=1, max_length=32)
    limitations: tuple[Symbol, ...] = Field(min_length=1, max_length=32)


class ReportCheckResult(ReportCheckPayload):
    """Self-identifying output must still be protected and rechecked by the actual publisher."""

    result_sha256: SHA256

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        """Reject altered self-identifying data without mistaking integrity for authority."""
        if len({row.criterion_id for row in self.criteria}) != len(self.criteria):
            raise ValueError("Check criteria must have exact unique identities")
        expected = (
            "reject"
            if any(row.verdict == "reject" for row in self.criteria)
            else (
                "inconclusive"
                if any(row.verdict == "inconclusive" for row in self.criteria)
                else "pass"
            )
        )
        if self.verdict != expected or self.result_sha256 != canonical_sha256(self.payload):
            raise ValueError(
                "Check result hash or aggregate verdict does not match its actual payload"
            )
        return self

    @property
    def payload(self) -> ReportCheckPayload:
        """Return exactly the immutable payload covered by result_sha256."""
        return ReportCheckPayload.model_validate(self.model_dump(exclude={"result_sha256"}))
