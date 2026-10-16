"""Hash-bound private C bodies and prompt-free metadata; decoding grants no permission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from nexus.builder.contracts import RepositoryPin
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import SHA256, ValueContract
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_intent import PreparedCodingRequest
from nexus.company.management.coding_repository import CodingRepositorySelection
from nexus.company.management.coding_sources import CodingSourceRef
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.planning_prepared_contracts import PlanningModelParameters, encoded
from nexus.harness.model_authorizer_contracts import model_action_parameters

BODY_LIMIT, HEADER_LIMIT = 524_288, 32_768
BODY_REVISION, HEADER_REVISION = "coding-prepared-body-v1", "coding-prepared-header-v1"
PREFIX = "coding.prepared:"


def _ids(action: UUID, request: str, purpose: str) -> tuple[UUID, UUID]:
    artifact = uuid5(action, purpose)
    return artifact, uuid5(artifact, request)


def repository_selection(prepared: PreparedCodingRequest) -> CodingRepositorySelection:
    """Exact original server nomination, not evidence that any read actually happened."""
    return CodingRepositorySelection(
        company_id=prepared.request.company_id,
        source=prepared.binding.source,
        files=tuple(row.git for row in prepared.sources),
        allowed_write_paths=prepared.binding.allowed_write_paths,
    )


class CodingPreparedHeader(ValueContract):
    """Small prompt-free private metadata, checked against actual native/source facts."""

    format: Literal["coding-prepared.header.v1"] = "coding-prepared.header.v1"
    company_id: UUID
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    actor_id: UUID
    workspace_id: UUID
    owner_id: UUID
    registration_sha256: SHA256
    root_task_id: UUID
    root_run_id: UUID
    root_registration_sha256: SHA256
    procedure_id: UUID
    admission_sha256: SHA256
    goal: GoalRevisionRef
    plan: PlanRevisionRef
    request_sha256: SHA256
    input_recipe_sha256: SHA256
    registry_sha256: SHA256
    model_sha256: SHA256
    model_parameters_sha256: SHA256
    parameters: PlanningModelParameters
    context_manifest_sha256: SHA256
    repository_source: RepositoryPin
    repository_selection_sha256: SHA256
    allowed_write_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    code_sources: tuple[CodingSourceRef, ...] = Field(min_length=1, max_length=20)
    contributors: tuple[ResourceGeneration, ...] = Field(min_length=1, max_length=32)
    source_heads: tuple[SourceHead, ...] = Field(min_length=1, max_length=32)
    body: ArtifactRevisionRef

    @model_validator(mode="after")
    def closed_header(self) -> Self:
        selection = CodingRepositorySelection(
            company_id=self.company_id,
            source=self.repository_source,
            files=tuple(row.git for row in self.code_sources),
            allowed_write_paths=self.allowed_write_paths,
        )
        if (
            self.body.company_id != self.company_id
            or self.goal.company_id != self.company_id
            or self.plan.company_id != self.company_id
            or self.root_task_id == self.task_id
            or (self.body.artifact_id, self.body.artifact_revision_id)
            != _ids(self.action_id, self.request_sha256, BODY_REVISION)
            or self.body.revision != BODY_REVISION
            or self.body.byte_length > BODY_LIMIT
            or self.parameters.request_hash != self.request_sha256
            or self.parameters.attempt_id != self.action_id
            or any(
                row.company_id != self.company_id
                for row in (*self.contributors, *self.source_heads)
            )
            or len({row.resource_id for row in self.contributors}) != len(self.contributors)
            or len({row.source_id for row in self.source_heads}) != len(self.source_heads)
            or any(row.source.company_id != self.company_id for row in self.code_sources)
        ):
            raise ValueError("Coding header scope/keys/source closure differs")
        if canonical_sha256(selection) != self.repository_selection_sha256:
            raise ValueError("Coding repository header nomination differs")
        return self


class CodingPreparedRef(ValueContract):
    company_id: UUID
    action_id: UUID
    request_sha256: SHA256
    header: ArtifactRevisionRef

    @model_validator(mode="after")
    def exact_key(self) -> Self:
        if (
            self.header.company_id,
            self.header.artifact_id,
            self.header.artifact_revision_id,
            self.header.revision,
        ) != (
            self.company_id,
            *_ids(self.action_id, self.request_sha256, HEADER_REVISION),
            HEADER_REVISION,
        ) or self.header.byte_length > HEADER_LIMIT:
            raise ValueError("Coding header reference differs from its deterministic key")
        return self

    @property
    def condition(self) -> ResourceRevision:
        """Exact new native condition; it confers no SDK/lease permission by itself."""
        return ResourceRevision(
            resource=f"{PREFIX}{self.action_id}",
            revision=f"sha256:{self.header.sha256}:bytes:{self.header.byte_length}",
        )


@dataclass(frozen=True, slots=True, eq=False)
class StoredCodingRequest:
    """Store checks issuance identity; constructing this dataclass conveys no proof."""

    prepared: PreparedCodingRequest
    reference: CodingPreparedRef
    header: CodingPreparedHeader
    read_end_us: int


@dataclass(frozen=True, slots=True)
class CodingHeaderRead:
    header: CodingPreparedHeader
    reference: CodingPreparedRef
    source_signature: str
    read_end_us: int


def encode_prepared(prepared: PreparedCodingRequest) -> tuple[bytes, ArtifactRevisionRef]:
    prepared = PreparedCodingRequest.model_validate_json(prepared.model_dump_json(by_alias=True))
    raw = encoded(prepared, BODY_LIMIT)
    artifact, revision = _ids(prepared.request.action_id, prepared.request_sha256, BODY_REVISION)
    return raw, ArtifactRevisionRef(
        company_id=prepared.request.company_id,
        artifact_id=artifact,
        artifact_revision_id=revision,
        revision=BODY_REVISION,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )


def header_for(
    prepared: PreparedCodingRequest,
    body: ArtifactRevisionRef,
    *,
    owner_id: UUID,
    registration_sha256: str,
    root_task_id: UUID,
    root_run_id: UUID,
    root_registration_sha256: str,
    procedure_id: UUID,
) -> CodingPreparedHeader:
    call, binding, manifest = prepared.request, prepared.binding, prepared.context.manifest
    whole = prepared.input_estimate.whole_request
    if whole is None:
        raise ValueError("Coding header requires the complete original model financial proof")
    return CodingPreparedHeader(
        company_id=call.company_id,
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        run_id=binding.run_id,
        actor_id=call.actor_id,
        workspace_id=binding.workspace_id,
        owner_id=owner_id,
        registration_sha256=registration_sha256,
        root_task_id=root_task_id,
        root_run_id=root_run_id,
        root_registration_sha256=root_registration_sha256,
        procedure_id=procedure_id,
        admission_sha256=prepared.admission_sha256,
        goal=binding.goal,
        plan=binding.plan,
        request_sha256=prepared.request_sha256,
        input_recipe_sha256=canonical_sha256(prepared.input_recipe),
        registry_sha256=whole.registry_sha256,
        model_sha256=whole.model_sha256,
        model_parameters_sha256=prepared.model_parameters_sha256,
        parameters=PlanningModelParameters.model_validate_json(
            json.dumps(model_action_parameters(call, prepared.input_recipe))
        ),
        context_manifest_sha256=binding.context_manifest_sha256,
        repository_source=binding.source,
        repository_selection_sha256=canonical_sha256(repository_selection(prepared)),
        allowed_write_paths=binding.allowed_write_paths,
        code_sources=prepared.sources,
        contributors=manifest.contributors,
        source_heads=manifest.source_heads,
        body=body,
    )


def header_reference(header: CodingPreparedHeader) -> tuple[CodingPreparedRef, bytes]:
    header = CodingPreparedHeader.model_validate_json(header.model_dump_json())
    raw = encoded(header, HEADER_LIMIT)
    artifact, revision = _ids(header.action_id, header.request_sha256, HEADER_REVISION)
    return CodingPreparedRef(
        company_id=header.company_id,
        action_id=header.action_id,
        request_sha256=header.request_sha256,
        header=ArtifactRevisionRef(
            company_id=header.company_id,
            artifact_id=artifact,
            artifact_revision_id=revision,
            revision=HEADER_REVISION,
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        ),
    ), raw


def prepared_reference(action: ActionProposal) -> CodingPreparedRef:
    """Select only the exact action-bound C marker; never strip unknown conditions."""
    parameters = PlanningModelParameters.model_validate_json(json.dumps(action.parameters))
    markers = tuple(row for row in action.preconditions if row.resource.startswith(PREFIX))
    if len(markers) != 1 or markers[0].resource != f"{PREFIX}{action.action_id}":
        raise ValueError("Coding action requires its one exact stored preparation")
    pieces = markers[0].revision.split(":")
    if (
        len(pieces) != 4
        or pieces[0] != "sha256"
        or pieces[2] != "bytes"
        or not pieces[3].isdecimal()
    ):
        raise ValueError("Coding marker is not its exact bounded hash/length")
    artifact, revision = _ids(action.action_id, parameters.request_hash, HEADER_REVISION)
    result = CodingPreparedRef(
        company_id=action.company_id,
        action_id=action.action_id,
        request_sha256=parameters.request_hash,
        header=ArtifactRevisionRef(
            company_id=action.company_id,
            artifact_id=artifact,
            artifact_revision_id=revision,
            revision=HEADER_REVISION,
            sha256=pieces[1],
            byte_length=int(pieces[3]),
        ),
    )
    if result.condition != markers[0]:
        raise ValueError("Coding marker is not canonical")
    return result


def decode_header(raw: bytes, reference: CodingPreparedRef) -> CodingPreparedHeader:
    if not 0 < len(raw) <= HEADER_LIMIT:
        raise ValueError("Coding header exceeds its byte boundary")
    header = CodingPreparedHeader.model_validate_json(raw)
    if header_reference(header) != (reference, raw):
        raise ValueError("Coding metadata bytes differ from actual native marker")
    return header


def require_body(header: CodingPreparedHeader, raw: bytes) -> PreparedCodingRequest:
    if not 0 < len(raw) <= BODY_LIMIT:
        raise ValueError("Coding body exceeds its byte boundary")
    header = CodingPreparedHeader.model_validate_json(header.model_dump_json())
    prepared = PreparedCodingRequest.model_validate_json(raw)
    observed, body = encode_prepared(prepared)
    expected = header_for(
        prepared,
        body,
        owner_id=header.owner_id,
        registration_sha256=header.registration_sha256,
        root_task_id=header.root_task_id,
        root_run_id=header.root_run_id,
        root_registration_sha256=header.root_registration_sha256,
        procedure_id=header.procedure_id,
    )
    if raw != observed or header != expected:
        raise ValueError("Complete coding body differs from its source-authorized header")
    return prepared
