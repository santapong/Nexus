"""Declared identity parsing: exact raw UTF8 text, bounded chunks and byte citations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
from itertools import pairwise
from multiprocessing.connection import Connection
from typing import NoReturn
from uuid import uuid5

from nexus.company.brain.base import ValueContract
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    EvidenceRecord,
    ParseRevisionRecord,
    SourceChunkRecord,
    SourceRevisionRecord,
    UTF8Span,
)


class ParseRejectedError(ValueError):
    """Fixed non-content reason is safe for quarantine metadata and bounded logs."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class ParsedSource(ValueContract):
    parse: ParseRevisionRecord
    chunks: tuple[SourceChunkRecord, ...]
    evidence: tuple[EvidenceRecord, ...]


def _reject_json_constant(_: str) -> NoReturn:
    raise ValueError("Unsupported non-finite JSON constant")


def _json_shape(text: str) -> None:
    depth, quoted, escaped = 0, False, False
    for character in text:
        if escaped:
            escaped = False
        elif quoted and character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted and character in "[{":
            depth += 1
            if depth > 64:
                raise ParseRejectedError("invalid_json")
        elif not quoted and character in "]}":
            depth -= 1
    try:
        json.loads(text, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        raise ParseRejectedError("invalid_json") from exc


def _sections(
    raw: bytes, spans: tuple[UTF8Span, ...]
) -> tuple[tuple[int, int, UTF8Span | None], ...]:
    """Unbounded structural windows become bounded evidence only after UTF8-safe splitting."""
    if len(spans) > 256:
        raise ParseRejectedError("chunk_limit")
    if not spans:
        boundaries, offset = [0], 0
        for line in raw.splitlines(keepends=True):
            if line.lstrip().startswith(b"#") and offset:
                boundaries.append(offset)
                if len(boundaries) > 256:
                    raise ParseRejectedError("chunk_limit")
            offset += len(line)
        boundaries.append(len(raw))
        return tuple((a, b, None) for a, b in pairwise(boundaries))
    cursor = 0
    result: list[tuple[int, int, UTF8Span | None]] = []
    for span in spans:
        if span.start_byte < cursor or span.end_byte > len(raw):
            raise ParseRejectedError("parse_failed")
        try:
            raw[: span.start_byte].decode("utf-8")
            raw[span.start_byte : span.end_byte].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseRejectedError("parse_failed") from exc
        if span.start_byte > cursor:
            result.append((cursor, span.start_byte, None))
        result.append((span.start_byte, span.end_byte, span))
        cursor = span.end_byte
    if cursor < len(raw):
        result.append((cursor, len(raw), None))
    return tuple(result)


def _ranges(
    raw: bytes, windows: tuple[tuple[int, int, UTF8Span | None], ...], maximum: int
) -> tuple[UTF8Span, ...]:
    result = []
    for start, stop, section in windows:
        while start < stop:
            end = min(start + maximum, stop)
            while end < stop and raw[end] & 0xC0 == 0x80:
                end -= 1
            if end <= start:
                raise ParseRejectedError("parse_failed")
            result.append(
                UTF8Span(
                    start_byte=start,
                    end_byte=end,
                    section=section.section if section else None,
                    path=section.path if section else None,
                    page=section.page if section else None,
                )
            )
            start = end
    return tuple(result)


def parse_identity(
    source: SourceRevisionRecord,
    artifact: ArtifactRevisionRecord,
    policy: SourcePolicy,
    *,
    sections: tuple[UTF8Span, ...] = (),
) -> ParsedSource:
    """Pure bounded identity parse; caller runs outside any company mutex."""
    if (policy.parser_version, policy.chunker_version) != ("utf8-identity-v1", "utf8-sections-v1"):
        raise ParseRejectedError("unsupported_recipe")
    if artifact.media_type != policy.media_type:
        raise ParseRejectedError("unsupported_media")
    if (source.company_id, source.artifact.artifact_revision_id, source.artifact.sha256) != (
        artifact.company_id,
        artifact.artifact_revision_id,
        artifact.sha256,
    ):
        raise ParseRejectedError("parse_failed")
    raw = artifact.raw_text.encode("utf-8")
    if len(raw) > 1_048_576:
        raise ParseRejectedError("parsed_too_large")
    if artifact.media_type == "application/json":
        _json_shape(artifact.raw_text)
    spans = _ranges(raw, _sections(raw, sections), policy.chunk_bytes)
    if len(spans) > policy.max_chunks:
        raise ParseRejectedError("chunk_limit")
    parse_id = uuid5(
        source.source_revision_id, f"parse:{policy.parser_version}:{policy.chunker_version}"
    )
    parsed = ParseRevisionRecord(
        company_id=source.company_id,
        parse_revision_id=parse_id,
        source=source,
        parser_version=policy.parser_version,
        chunker_version=policy.chunker_version,
        canonical_text=artifact.raw_text,
        canonical_sha256=artifact.sha256,
        recorded_at=source.ingested_at,
    )
    chunks, evidence = _citations(source, artifact, parsed, spans)
    return ParsedSource(parse=parsed, chunks=chunks, evidence=evidence)


def _citations(
    source: SourceRevisionRecord,
    artifact: ArtifactRevisionRecord,
    parsed: ParseRevisionRecord,
    spans: tuple[UTF8Span, ...],
) -> tuple[tuple[SourceChunkRecord, ...], tuple[EvidenceRecord, ...]]:
    raw = artifact.raw_text.encode("utf-8")
    chunks, evidence = [], []
    for ordinal, span in enumerate(spans):
        text = raw[span.start_byte : span.end_byte].decode("utf-8")
        digest = hashlib.sha256(text.encode()).hexdigest()
        chunk_id = uuid5(
            parsed.parse_revision_id, f"chunk:{ordinal}:{span.start_byte}:{span.end_byte}"
        )
        chunks.append(
            SourceChunkRecord(
                company_id=source.company_id,
                chunk_id=chunk_id,
                parse_revision_id=parsed.parse_revision_id,
                source=source,
                ordinal=ordinal,
                parsed_span=span,
                text=text,
                sha256=digest,
            )
        )
        evidence.append(
            EvidenceRecord(
                company_id=source.company_id,
                evidence_id=uuid5(chunk_id, "evidence:raw-utf8-v1"),
                source=source,
                artifact=artifact,
                raw_span=span,
                span_sha256=digest,
                source_event=source.source_event,
                ingested_at=source.ingested_at,
                parse_revision_id=parsed.parse_revision_id,
                parsed_span=span,
                chunk_id=chunk_id,
            )
        )
    return tuple(chunks), tuple(evidence)


def _parse_child(
    connection: Connection,
    source: SourceRevisionRecord,
    artifact: ArtifactRevisionRecord,
    policy: SourcePolicy,
    sections: tuple[UTF8Span, ...],
) -> None:
    """Trusted fixed parser process; no model/network/authority code runs in this worker."""
    try:
        connection.send((parse_identity(source, artifact, policy, sections=sections), None))
    except ParseRejectedError as exc:
        connection.send((None, exc.reason_code))
    except Exception:
        connection.send((None, "parse_failed"))
    finally:
        connection.close()


async def parse_isolated(
    source: SourceRevisionRecord,
    artifact: ArtifactRevisionRecord,
    policy: SourcePolicy,
    *,
    sections: tuple[UTF8Span, ...] = (),
) -> ParsedSource:
    """Terminate a timed-out isolated parser; a detached thread cannot retain CPU indefinitely."""
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_child, args=(sending, source, artifact, policy, sections)
    )
    process.start()
    sending.close()
    try:
        result, reason = await asyncio.wait_for(
            asyncio.to_thread(receiving.recv), timeout=policy.parse_timeout_seconds
        )
        if reason is not None:
            raise ParseRejectedError(reason)
        if not isinstance(result, ParsedSource):
            raise ParseRejectedError("parse_failed")
        return result
    except TimeoutError as exc:
        raise ParseRejectedError("parse_timeout") from exc
    except EOFError as exc:
        raise ParseRejectedError("parse_failed") from exc
    finally:
        if process.is_alive():
            process.terminate()
        await asyncio.to_thread(process.join, 1)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 1)
        receiving.close()
