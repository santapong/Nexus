"""Exact supplied source spans and original date precision, without native READ affirmation."""

from datetime import datetime, timedelta

from nexus.company.cycle_artifacts.common import digest
from nexus.company.management.check_contracts import CitationCheckSource, SourceQuoteClaim


def quote_sources(
    sources: tuple[CitationCheckSource, ...], observed_at: datetime
) -> tuple[SourceQuoteClaim, ...]:
    if (
        not 1 <= len(sources) <= 16
        or observed_at.utcoffset() is None
        or len({row.evidence.evidence_id for row in sources}) != len(sources)
    ):
        raise ValueError("Cycle citation source count/clock differs")
    checked = tuple(
        CitationCheckSource.model_validate(row.model_dump(warnings=False)) for row in sources
    )
    if sum(len(row.raw_text.encode()) for row in checked) > 8388608:
        raise ValueError("Complete cycle citation bytes exceed eight MiB")
    result = []
    for source in checked:
        row, span = source.evidence, _validated_span(source, observed_at)
        result.append(
            SourceQuoteClaim(
                kind="source_quote",
                evidence_id=row.evidence_id,
                source_revision_id=row.source.source_revision_id,
                artifact_revision_id=row.artifact.artifact_revision_id,
                span_sha256=row.span_sha256,
                quote=span.decode("utf8"),
                source_event=row.source_event,
                source_state="current",
                freshness="fresh",
            )
        )
    return tuple(result)


def _validated_span(source: CitationCheckSource, observed_at: datetime) -> bytes:
    row, head, raw = source.evidence, source.head, source.raw_text.encode()
    if source.source_policy is None:
        raise ValueError("Cycle supplied source policy description is missing")
    span = raw[row.raw_span.start_byte : row.raw_span.end_byte]
    if (
        len(raw) != row.artifact.byte_length
        or digest(raw) != row.artifact.sha256
        or not 0 < len(span) <= 16384
        or len(span) != row.raw_span.end_byte - row.raw_span.start_byte
        or digest(span) != row.span_sha256
        or b"\0" in raw
        or len(raw) > 2097152
        or len(raw) > source.source_policy.max_bytes
        or head.current != row.source
        or head.availability != "available"
        or max(head.observed_at, row.ingested_at) > observed_at
        or (head.fresh_until is not None and head.fresh_until <= observed_at)
    ):
        raise ValueError("Cycle supplied source bytes/head/date/span differ")
    seconds = source.source_policy.freshness_seconds
    expected = head.observed_at + timedelta(seconds=seconds) if seconds is not None else None
    if head.fresh_until != expected:
        raise ValueError("Cycle supplied source policy/freshness window differs")
    return span
