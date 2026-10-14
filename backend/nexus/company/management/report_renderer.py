"""Deterministic report rendering from server-resolved sources/ledger, not model narrative truth."""

import hashlib
from datetime import datetime

from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.check_contracts import (
    AcceptedWorkClaim,
    CitationCheckSource,
    SourceQuoteClaim,
    StructuredInternalReport,
)
from nexus.company.management.report_rules import OperatingProjection


def render_native_report(
    operating: OperatingProjection,
    sources: tuple[CitationCheckSource, ...],
    *,
    observed_at: datetime,
) -> StructuredInternalReport:
    """Preserve exact quoted bytes/date precision and actual accepted-work identities."""
    require_acceptance(0 < len(sources) <= 32 and observed_at.utcoffset() is not None)
    quotes = tuple(_quote(source, observed_at) for source in sources)
    require_acceptance(len({row.evidence_id for row in quotes}) == len(quotes))
    accepted = tuple(
        AcceptedWorkClaim(
            kind="accepted_work", task_id=row.work.task_id, acceptance_id=row.acceptance_id
        )
        for row in operating.snapshot.work
        if row.work.task_id in operating.accepted_task_ids and row.acceptance_id is not None
    )
    return StructuredInternalReport(
        schema_version="nexus.company.internal-report.v1",
        company_id=operating.company_id,
        operating=operating,
        claims=(*quotes, *accepted),
    )


def _quote(source: CitationCheckSource, observed_at: datetime) -> SourceQuoteClaim:
    record, head = source.evidence, source.head
    raw = source.raw_text.encode()
    span = raw[record.raw_span.start_byte : record.raw_span.end_byte]
    require_acceptance(
        len(raw) == record.artifact.byte_length
        and hashlib.sha256(raw).hexdigest() == record.artifact.sha256
        and len(span) == record.raw_span.end_byte - record.raw_span.start_byte
        and hashlib.sha256(span).hexdigest() == record.span_sha256
        and record.source.source_id == head.source_id
        and 0 < len(span) <= 16384
    )
    freshness = "fresh"
    if head.availability != "available":
        freshness = "unavailable"
    elif head.fresh_until is None:
        require_acceptance(
            source.source_policy is not None and source.source_policy.freshness_seconds is None
        )
    elif head.fresh_until <= observed_at:
        freshness = "stale"
    return SourceQuoteClaim.model_validate(
        {
            "kind": "source_quote",
            "evidence_id": record.evidence_id,
            "source_revision_id": record.source.source_revision_id,
            "artifact_revision_id": record.artifact.artifact_revision_id,
            "span_sha256": record.span_sha256,
            "quote": span.decode("utf-8"),
            "source_event": record.source_event,
            "source_state": "current" if record.source == head.current else "historical",
            "freshness": freshness,
        }
    )
