"""Bounded coding content and historical selectors; none grant publication or execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from nexus.builder.contracts import BuilderArtifact, RepositoryPin
from nexus.builder.patch_text import HEADER, TextPatch, apply_text, parse_patch
from nexus.builder.snapshot import source_path
from nexus.company.brain.base import SHA256, ValueContract
from nexus.company.brain.context import ContextManifest
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument
from nexus.harness.model_client_contracts import GovernedModelResult

MAX_CODE_PATCH_BYTES = 32_768
MAX_CODE_CONTENT_BYTES = 65_536
Statement = Annotated[str, Field(min_length=1, max_length=1024)]


def _text(value: str, maximum: int) -> str:
    if not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError("Coding text is blank or exceeds its UTF-8 byte bound")
    return value


def _patch(value: str, allowed: tuple[str, ...]) -> tuple[TextPatch, ...]:
    raw = value.encode("utf-8")
    return parse_patch(raw, hashlib.sha256(raw).hexdigest(), allowed)


class CodeChangeContent(ValueContract):
    """Untrusted model data only; server originals and policy are separate inputs."""

    patch: Annotated[str, Field(min_length=1, max_length=MAX_CODE_PATCH_BYTES)]
    explanation: Annotated[str, Field(min_length=1, max_length=8192)]
    questions: tuple[Statement, ...] = Field(max_length=16)
    evidence_ids: tuple[UUID, ...] = Field(max_length=20)

    @field_validator("patch")
    @classmethod
    def patch_syntax(cls, value: str) -> str:
        _text(value, MAX_CODE_PATCH_BYTES)
        # Model paths permit syntax parsing only; validate_code_change supplies real policy.
        headers = tuple(HEADER.fullmatch(line) for line in value.splitlines(keepends=True))
        _patch(value, tuple(match[1] for match in headers if match is not None))
        return value

    @field_validator("explanation")
    @classmethod
    def bounded_explanation(cls, value: str) -> str:
        return _text(value, 8192)

    @field_validator("questions")
    @classmethod
    def bounded_questions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_text(item, 1024) for item in value)

    @model_validator(mode="after")
    def bounded_content(self) -> Self:
        if len(set(self.questions)) != len(self.questions) or len(set(self.evidence_ids)) != len(
            self.evidence_ids
        ):
            raise ValueError("Coding questions and evidence references must be distinct")
        # Match JsonSchemaDocument.validate_output, including ASCII escape expansion.
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_CODE_CONTENT_BYTES:
            raise ValueError("Complete canonical coding output exceeds the gateway byte bound")
        return self


class CodingBinding(ValueContract):
    """Immutable server-captured refs; current source/authority checks remain mandatory."""

    goal: GoalRevisionRef
    plan: PlanRevisionRef
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    actor_id: UUID
    workspace_id: UUID
    source: RepositoryPin
    source_files: tuple[BuilderArtifact, ...] = Field(min_length=1, max_length=32)
    allowed_write_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    context_manifest_sha256: SHA256

    @model_validator(mode="after")
    def fixed_source_policy(self) -> Self:
        paths = tuple(row.path for row in self.source_files)
        if (
            self.goal.company_id != self.plan.company_id
            or len(set(paths)) != len(paths)
            or len(set(self.allowed_write_paths)) != len(self.allowed_write_paths)
            or not set(self.allowed_write_paths) <= set(paths)
            or sum(row.byte_length for row in self.source_files) > 65_536
        ):
            raise ValueError("Coding source closure or explicit existing-file policy differs")
        for path in paths:
            source_path(path)
        return self

    def require_manifest(self, manifest: ContextManifest) -> None:
        """Join the exact original context and registered actor/work identifiers."""
        if canonical_sha256(manifest) != self.context_manifest_sha256 or (
            manifest.company_id,
            manifest.task_id,
            manifest.task_trace_id,
            manifest.actor_id,
            manifest.principal_id,
        ) != (self.goal.company_id, self.task_id, self.trace_id, self.actor_id, self.actor_id):
            raise ValueError("Coding context differs from its original server binding")


def _context(
    binding: CodingBinding, manifest: ContextManifest
) -> tuple[CodingBinding, ContextManifest]:
    binding = CodingBinding.model_validate_json(binding.model_dump_json())
    manifest = ContextManifest.model_validate_json(manifest.model_dump_json())
    binding.require_manifest(manifest)
    return binding, manifest


def validate_code_change(
    content: CodeChangeContent,
    binding: CodingBinding,
    *,
    manifest: ContextManifest,
    originals: Mapping[str, bytes],
) -> tuple[TextPatch, ...]:
    """Pure exact application check; no source reads, mutation, fallback or acceptance claim."""
    content = CodeChangeContent.model_validate_json(content.model_dump_json())
    binding, manifest = _context(binding, manifest)
    allowed_evidence = {
        row.handle.evidence_id for row in manifest.inclusions if row.disposition != "stale"
    }
    if not set(content.evidence_ids) <= allowed_evidence:
        raise ValueError("Coding content cites evidence absent from its actual context")
    captured = dict(originals)
    if set(captured) != {row.path for row in binding.source_files}:
        raise ValueError("Coding originals must match the complete pinned file closure")
    for row in binding.source_files:
        raw = captured[row.path]
        if (
            type(raw) is not bytes
            or len(raw) != row.byte_length
            or hashlib.sha256(raw).hexdigest() != row.sha256
        ):
            raise ValueError("Coding original bytes differ from their source pin")
        raw.decode("utf-8")
    changes = _patch(content.patch, binding.allowed_write_paths)
    for change in changes:
        if change.operation != "modify" or change.path not in binding.allowed_write_paths:
            raise ValueError("This coding profile modifies only explicit existing pinned files")
        apply_text(captured[change.path], change)
    return changes


def coding_schema(binding: CodingBinding, *, manifest: ContextManifest) -> JsonSchemaDocument:
    """Closed content plus recoverable server data; vendor acceptance is unqualified."""
    binding, manifest = _context(binding, manifest)
    document = CodeChangeContent.model_json_schema()
    document["$comment"] = json.dumps(
        {
            "version": "nexus.company.coding-binding.v1",
            "binding": binding.model_dump(mode="json"),
            "sha256": canonical_sha256(binding),
            "context_manifest": manifest.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return JsonSchemaDocument(schema_json=json.dumps(document))


def coding_annotation(schema: JsonSchemaDocument) -> tuple[CodingBinding, ContextManifest]:
    """Recover only the exact closed server schema, never a model-posted permission."""
    schema = JsonSchemaDocument.model_validate_json(schema.model_dump_json(by_alias=True))
    annotation = json.loads(json.loads(schema.document).get("$comment", "{}"))
    if (
        not isinstance(annotation, dict)
        or set(annotation) != {"version", "binding", "sha256", "context_manifest"}
        or annotation["version"] != "nexus.company.coding-binding.v1"
    ):
        raise ValueError("Coding annotation requires its complete exact original refs")
    binding = CodingBinding.model_validate_json(json.dumps(annotation["binding"]))
    manifest = ContextManifest.model_validate_json(json.dumps(annotation["context_manifest"]))
    if annotation["sha256"] != canonical_sha256(binding) or schema != coding_schema(
        binding, manifest=manifest
    ):
        raise ValueError("Coding annotation or schema differs from its exact server inputs")
    return binding, manifest


class CodingCandidate(ValueContract):
    """Historical model-envelope selectors; not a Brain artifact, current plan or permit."""

    status: Literal["historical_candidate"] = "historical_candidate"
    binding: CodingBinding
    manifest: ContextManifest
    request_id: UUID
    action_id: UUID
    request_sha256: SHA256
    action_proposal_sha256: SHA256
    content: CodeChangeContent
    artifact: ArtifactRef
    receipt_id: UUID

    @model_validator(mode="after")
    def historical_scope(self) -> Self:
        binding, manifest = _context(self.binding, self.manifest)
        content = CodeChangeContent.model_validate_json(self.content.model_dump_json())
        if (
            self.artifact.company_id != binding.goal.company_id
            or binding.actor_id not in self.artifact.allowed_principals
            or self.artifact.revision != "model-result-envelope-v1"
            or not set(content.evidence_ids)
            <= {row.handle.evidence_id for row in manifest.inclusions if row.disposition != "stale"}
        ):
            raise ValueError("Coding candidate context or protected model reference differs")
        return self


CodingDenial = Literal[
    "model_outcome", "evidence_unavailable", "evidence_mismatch", "invalid_content"
]


class CodingAttempt(ValueContract):
    """Domain denial preserves actual native billing; it does not refund or retry."""

    governed: GovernedModelResult
    candidate: CodingCandidate | None
    denial: CodingDenial | None
    stop_required: bool = True
    company_completed: Literal[False] = False

    @model_validator(mode="after")
    def descriptive_result(self) -> Self:
        governed = GovernedModelResult.model_validate_json(self.governed.model_dump_json())
        if (self.candidate is None) != (self.denial is not None) or self.stop_required != (
            self.candidate is None or governed.stop_required
        ):
            raise ValueError("Denied coding content must stop and cannot carry a candidate")
        if self.candidate is not None:
            candidate = CodingCandidate.model_validate_json(self.candidate.model_dump_json())
            recorded = governed.recorded
            result = governed.provider_result
            if (
                recorded is None
                or governed.stop_required
                or result.status != "response"
                or governed.release_status != "released"
                or recorded.billing != "known"
                or recorded.stop_required
                or recorded.receipt_id != candidate.receipt_id
                or recorded.artifact != candidate.artifact
                or result.request_id != candidate.request_id
                or result.structured_json is None
                or CodeChangeContent.model_validate_json(result.structured_json)
                != candidate.content
            ):
                raise ValueError("Coding candidate lacks known recorded released provenance")
        return self
