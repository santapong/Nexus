"""Complete authorized workspace code, never code appended outside the original manifest."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections.abc import Mapping
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderArtifact
from nexus.builder.snapshot import MAX_ARCHIVE_BYTES, archive_members
from nexus.company.brain.base import ValueContract
from nexus.company.brain.context import AssembledContext, ContextInclusion, ContextSelection
from nexus.company.brain.context_render import RENDER_RECIPE, _encoded, _system
from nexus.company.brain.git_source import GitSnapshotSpec
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRecord,
    EvidenceRef,
    SourceRevisionRef,
)
from nexus.company.management.coding_content import CodingBinding


class CodingSourceRef(ValueContract):
    """Server mapping of an actual registered Git source and its complete raw spans."""

    file: BuilderArtifact
    git: GitSnapshotSpec
    source: SourceRevisionRef
    artifact: ArtifactRevisionRef
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        if (
            self.git.company_id != self.source.company_id
            or self.artifact.company_id != self.source.company_id
            or any(row.company_id != self.source.company_id for row in self.evidence)
            or self.git.source_id != self.source.source_id
            or self.source.revision != self.git.commit
            or self.git.path != self.file.path
            or (self.file.sha256, self.file.byte_length) != (self.git.sha256, self.git.byte_length)
            or (self.file.sha256, self.file.byte_length)
            != (self.artifact.sha256, self.artifact.byte_length)
            or len(set(self.evidence)) != len(self.evidence)
        ):
            raise ValueError("Coding file/Git/source/artifact/evidence mapping differs")
        return self


def _refs(sources: tuple[CodingSourceRef, ...]) -> tuple[CodingSourceRef, ...]:
    sources = tuple(CodingSourceRef.model_validate_json(row.model_dump_json()) for row in sources)
    if (
        not 1 <= len(sources) <= 20
        or any(
            len(set(values)) != len(values)
            for values in (
                tuple(row.file.path for row in sources),
                tuple(row.source.source_id for row in sources),
                tuple(row.artifact.artifact_revision_id for row in sources),
                tuple(ref.evidence_id for row in sources for ref in row.evidence),
            )
        )
        or sum(len(row.evidence) for row in sources) > 20
    ):
        raise ValueError("Coding source closure contains duplicate or excessive references")
    if len({row.source.company_id for row in sources}) != 1:
        raise ValueError("Coding sources cross companies")
    return sources


def coding_selection(sources: tuple[CodingSourceRef, ...]) -> ContextSelection:
    """Select explicit real workspace evidence for PersistentContextAssembler.assemble."""
    sources = _refs(sources)
    return ContextSelection(
        company_id=sources[0].source.company_id,
        workspace_files=tuple(ref for row in sources for ref in row.evidence),
    )


def _rendered(context: AssembledContext) -> dict[UUID, tuple[ContextInclusion, bytes]]:
    document: object = json.loads(context.input_text)
    if (
        context.manifest.render_recipe != RENDER_RECIPE
        or context.system_text != _system(context.manifest.authority)
        or not isinstance(document, dict)
        or set(document) != {"question", "untrusted_source_data"}
        or not isinstance(document["question"], str)
        or not document["question"].strip()
        or len(document["question"].encode()) > 2000
        or not isinstance(document["untrusted_source_data"], list)
        or context.input_text != _encoded(document)
    ):
        raise ValueError("Coding context is not the exact original Brain data rendering")
    inclusions = {row.handle.evidence_id: row for row in context.manifest.inclusions}
    if len(inclusions) != len(context.manifest.inclusions):
        raise ValueError("Coding manifest repeats a source inclusion")
    result: dict[UUID, tuple[ContextInclusion, bytes]] = {}
    for payload in document["untrusted_source_data"]:
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "trust",
                "purpose",
                "citation",
                "text",
                "source_state",
                "freshness",
                "authority_profile",
                "source_symbol",
                "external_key",
                "data_classification",
            }
            or not isinstance(payload["text"], str)
        ):
            raise ValueError("Coding context source data is incomplete")
        record = EvidenceRecord.model_validate_json(json.dumps(payload["citation"]))
        inclusion = inclusions.get(record.evidence_id)
        raw = payload["text"].encode("utf-8")
        if (
            inclusion is None
            or record.evidence_id in result
            or inclusion.handle.record != record
            or payload["trust"] != "untrusted_source_data"
            or payload["purpose"] != inclusion.purpose
            or payload["data_classification"] != inclusion.data_classification
            or len(raw) != inclusion.included_bytes
            or len(raw) != record.raw_span.end_byte - record.raw_span.start_byte
            or hashlib.sha256(raw).hexdigest() != record.span_sha256
        ):
            raise ValueError("Coding rendered bytes differ from actual context citations")
        result[record.evidence_id] = (inclusion, raw)
    if (
        set(result) != set(inclusions)
        or sum(len(row[1]) for row in result.values()) != context.manifest.materialized_bytes
    ):
        raise ValueError("Coding rendering omitted its exact manifest inclusions")
    return result


def require_coding_sources(
    binding: CodingBinding,
    context: AssembledContext,
    sources: tuple[CodingSourceRef, ...],
) -> Mapping[str, bytes]:
    """Check complete actual code in authorized context; no Git/tree/archive attestation."""
    binding = CodingBinding.model_validate_json(binding.model_dump_json())
    context = AssembledContext.model_validate_json(context.model_dump_json())
    binding.require_manifest(context.manifest)
    sources = _refs(sources)
    if tuple(row.file for row in sources) != binding.source_files or any(
        (row.source.company_id, row.git.commit) != (binding.goal.company_id, binding.source.commit)
        for row in sources
    ):
        raise ValueError("Coding context source closure differs from its frozen repository/files")
    rendered = _rendered(context)
    heads = {row.source_id: row for row in context.manifest.source_heads}
    required = {ref.evidence_id for row in sources for ref in row.evidence}
    if len(heads) != len(context.manifest.source_heads) or any(
        row.evidence.evidence_id in required for row in context.manifest.omissions
    ):
        raise ValueError("Coding source heads repeat or required input was declared omitted")
    result: dict[str, bytes] = {}
    payloads = {
        UUID(row["citation"]["evidence_id"]): row
        for row in json.loads(context.input_text)["untrusted_source_data"]
    }
    for source in sources:
        head = heads.get(source.source.source_id)
        if head is None or head.current != source.source or head.availability != "available":
            raise ValueError("Coding source is not its exact available current Brain head")
        parts = []
        for ref in source.evidence:
            included = rendered.get(ref.evidence_id)
            if included is None:
                raise ValueError("Required coding evidence was omitted from the prompt")
            inclusion, raw = included
            record, payload = inclusion.handle.record, payloads[ref.evidence_id]
            if (
                inclusion.purpose != "workspace"
                or inclusion.disposition != "included"
                or (record.source, record.artifact, record.source_event)
                != (source.source, source.artifact, source.git.source_event)
                or record.raw_span.path not in {None, source.file.path}
                or payload["source_state"] != "current"
                or payload["freshness"] == "stale"
                or (payload["source_symbol"], payload["external_key"])
                != (source.git.source_symbol, source.git.external_key)
                or source.source not in inclusion.handle.source_contributors
            ):
                raise ValueError("Coding evidence is partial, stale or belongs to another source")
            parts.append((record.raw_span.start_byte, record.raw_span.end_byte, raw))
        cursor, body = 0, bytearray()
        for start, end, raw in sorted(parts):
            if start != cursor:
                raise ValueError("Coding source raw spans have a gap or overlap")
            cursor = end
            body.extend(raw)
        raw = bytes(body)
        if (cursor, hashlib.sha256(raw).hexdigest()) != (
            source.file.byte_length,
            source.file.sha256,
        ):
            raise ValueError("Coding prompt does not contain the complete exact source file")
        raw.decode("utf-8")
        result[source.file.path] = raw
    return result


def require_coding_archive(
    raw: bytes, binding: CodingBinding, originals: Mapping[str, bytes]
) -> None:
    """Pure bounded tar/file-byte join only; Root must use actual committed_archive first.

    This function does not prove Git commit/tree. The concrete producer must retain
    its actual bounded read owner and immutable proof header before first approval.
    No extraction, filesystem access or archive bytes enter model input here.
    """
    binding = CodingBinding.model_validate_json(binding.model_dump_json())
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= MAX_ARCHIVE_BYTES
        or hashlib.sha256(raw).hexdigest() != binding.source.archive_sha256
    ):
        raise ValueError("Coding archive bytes/hash exceed their original pin")
    if set(originals) != {row.path for row in binding.source_files}:
        raise ValueError("Coding archive lacks its complete original file closure")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = {row.name: row for row in archive_members(archive) if row.isfile()}
        for source in binding.source_files:
            member, original = members.get(source.path), originals[source.path]
            if (
                member is None
                or type(original) is not bytes
                or member.size != source.byte_length
                or len(original) != source.byte_length
                or hashlib.sha256(original).hexdigest() != source.sha256
            ):
                raise ValueError("Coding archive selected file differs from its source pin")
            stream = archive.extractfile(member)
            if stream is None or stream.read(source.byte_length + 1) != original:
                raise ValueError("Coding archive file bytes differ from the actual code context")
