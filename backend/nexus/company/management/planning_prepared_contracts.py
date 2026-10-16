"""Hash-bound private planning preparation; metadata selectors confer no read or model permit."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, Field, model_validator

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import SHA256, Name, ValueContract
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.planning_intent import PreparedPlanningRequest
from nexus.harness.model_authorizer_contracts import model_action_parameters

BODY_LIMIT = 524_288
DESCRIPTOR_LIMIT = 32_768
PREFIX = "planning.prepared:"
BODY_REVISION = "planning-prepared-body-v1"
DESCRIPTOR_REVISION = "planning-prepared-descriptor-v1"


def encoded(value: BaseModel, limit: int) -> bytes:
    """Canonical alias-correct objects; ordered lists/tuples and exact Unicode are preserved."""
    raw = (
        json.dumps(
            value.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()
    if not 0 < len(raw) <= limit:
        raise ValueError("Complete planning preparation exceeds its byte bound")
    return raw


def _ids(action_id: UUID, request_sha256: str, purpose: str) -> tuple[UUID, UUID]:
    artifact = uuid5(action_id, purpose)
    return artifact, uuid5(artifact, request_sha256)


class PlanningModelParameters(ValueContract):
    """The exact existing nine model_action_parameters keys, without prompt text."""

    request_hash: SHA256
    request_id: UUID
    attempt_id: UUID
    registry_id: Name
    registry_revision: Name
    price_version: Name
    input_recipe_id: Name
    input_recipe_revision: Name
    input_recipe_hash: SHA256


class PlanningPreparedDescriptor(ValueContract):
    """Private metadata is read before source authorization; it contains no prompt/role text."""

    format: Literal["nexus.planning-prepared.descriptor.v1"] = (
        "nexus.planning-prepared.descriptor.v1"
    )
    company_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    workspace_id: UUID
    action_id: UUID
    run_id: UUID
    owner_id: UUID
    registration_sha256: SHA256
    request_sha256: SHA256
    input_recipe_sha256: SHA256
    parameters: PlanningModelParameters
    goal: GoalRevisionRef
    plan_id: UUID
    expected_plan_revision_id: UUID | None
    context_manifest_sha256: SHA256
    body: ArtifactRevisionRef
    contributors: tuple[ResourceGeneration, ...] = Field(max_length=32)
    source_heads: tuple[SourceHead, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def closed_metadata(self) -> Self:
        expected = _ids(self.action_id, self.request_sha256, BODY_REVISION)
        if (
            (self.body.company_id, self.goal.company_id) != (self.company_id, self.company_id)
            or (self.body.artifact_id, self.body.artifact_revision_id) != expected
            or self.body.revision != BODY_REVISION
            or self.body.byte_length > BODY_LIMIT
            or self.parameters.request_hash != self.request_sha256
            or self.parameters.attempt_id != self.action_id
            or len({row.resource_id for row in self.contributors}) != len(self.contributors)
            or len({row.source_id for row in self.source_heads}) != len(self.source_heads)
            or any(
                row.company_id != self.company_id
                for row in (*self.contributors, *self.source_heads)
            )
        ):
            raise ValueError("Planning descriptor scope, keys or native metadata differ")
        return self


class PlanningPreparedRef(ValueContract):
    company_id: UUID
    action_id: UUID
    request_sha256: SHA256
    descriptor: ArtifactRevisionRef

    @model_validator(mode="after")
    def exact_key(self) -> Self:
        if (
            self.descriptor.company_id != self.company_id
            or (self.descriptor.artifact_id, self.descriptor.artifact_revision_id)
            != _ids(self.action_id, self.request_sha256, DESCRIPTOR_REVISION)
            or self.descriptor.revision != DESCRIPTOR_REVISION
            or self.descriptor.byte_length > DESCRIPTOR_LIMIT
        ):
            raise ValueError("Planning descriptor reference differs from its deterministic key")
        return self

    @property
    def condition(self) -> ResourceRevision:
        """Opaque hash metadata included in the existing full native action approval."""
        value = self.descriptor
        return ResourceRevision(
            resource=f"{PREFIX}{value.artifact_id}:{value.artifact_revision_id}",
            revision=f"sha256:{value.sha256}:bytes:{value.byte_length}",
        )


@dataclass(frozen=True, slots=True)
class StoredPlanningRequest:
    """Exact loaded data; the existing native model/context gates still own every SDK permit."""

    prepared: PreparedPlanningRequest
    reference: PlanningPreparedRef
    read_end_us: int  # Actual shortened original read cutoff; descriptive, never a permit.


def encode_prepared(prepared: PreparedPlanningRequest) -> tuple[bytes, ArtifactRevisionRef]:
    prepared = PreparedPlanningRequest.model_validate_json(prepared.model_dump_json(by_alias=True))
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


def descriptor_for(
    prepared: PreparedPlanningRequest,
    body: ArtifactRevisionRef,
    *,
    run_id: UUID,
    registration_sha256: str,
    owner_id: UUID,
) -> PlanningPreparedDescriptor:
    call, binding, manifest = prepared.request, prepared.binding, prepared.context.manifest
    return PlanningPreparedDescriptor(
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        workspace_id=prepared.scope.workspace_id,
        action_id=call.action_id,
        run_id=run_id,
        owner_id=owner_id,
        registration_sha256=registration_sha256,
        request_sha256=prepared.request_sha256,
        input_recipe_sha256=canonical_sha256(prepared.input_recipe),
        parameters=PlanningModelParameters.model_validate_json(
            json.dumps(model_action_parameters(call, prepared.input_recipe))
        ),
        goal=binding.goal,
        plan_id=binding.plan_id,
        expected_plan_revision_id=binding.expected_plan_revision_id,
        context_manifest_sha256=binding.context_manifest_sha256,
        body=body,
        contributors=manifest.contributors,
        source_heads=manifest.source_heads,
    )


def descriptor_reference(value: PlanningPreparedDescriptor) -> tuple[PlanningPreparedRef, bytes]:
    value = PlanningPreparedDescriptor.model_validate_json(value.model_dump_json())
    raw = encoded(value, DESCRIPTOR_LIMIT)
    artifact, revision = _ids(value.action_id, value.request_sha256, DESCRIPTOR_REVISION)
    descriptor = ArtifactRevisionRef(
        company_id=value.company_id,
        artifact_id=artifact,
        artifact_revision_id=revision,
        revision=DESCRIPTOR_REVISION,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    return PlanningPreparedRef(
        company_id=value.company_id,
        action_id=value.action_id,
        request_sha256=value.request_sha256,
        descriptor=descriptor,
    ), raw


def prepared_reference(action: ActionProposal) -> PlanningPreparedRef:
    """Read a single exact marker from the actual immutable native proposal, never a caller path."""
    parameters = PlanningModelParameters.model_validate_json(json.dumps(action.parameters))
    markers = tuple(row for row in action.preconditions if row.resource.startswith(PREFIX))
    if len(markers) != 1:
        raise ValueError("Planning action requires exactly one protected preparation")
    artifact, revision = _ids(action.action_id, parameters.request_hash, DESCRIPTOR_REVISION)
    pieces = markers[0].revision.split(":")
    if (
        markers[0].resource != f"{PREFIX}{artifact}:{revision}"
        or len(pieces) != 4
        or pieces[0] != "sha256"
        or pieces[2] != "bytes"
        or not pieces[3].isdecimal()
    ):
        raise ValueError("Planning preparation marker is not its exact native key")
    reference = PlanningPreparedRef(
        company_id=action.company_id,
        action_id=action.action_id,
        request_sha256=parameters.request_hash,
        descriptor=ArtifactRevisionRef(
            company_id=action.company_id,
            artifact_id=artifact,
            artifact_revision_id=revision,
            revision=DESCRIPTOR_REVISION,
            sha256=pieces[1],
            byte_length=int(pieces[3]),
        ),
    )
    if reference.condition != markers[0]:
        raise ValueError("Planning preparation marker is not canonically encoded")
    return reference


def decode_descriptor(raw: bytes, reference: PlanningPreparedRef) -> PlanningPreparedDescriptor:
    value = PlanningPreparedDescriptor.model_validate_json(raw)
    if descriptor_reference(value) != (reference, raw):
        raise ValueError("Actual planning descriptor bytes/hash differ from native approval")
    return value


def require_body(header: PlanningPreparedDescriptor, raw: bytes) -> PreparedPlanningRequest:
    """Full bytes and every descriptive field must match the source-authorized descriptor."""
    header = PlanningPreparedDescriptor.model_validate_json(header.model_dump_json())
    prepared = PreparedPlanningRequest.model_validate_json(raw)
    observed, reference = encode_prepared(prepared)
    expected = descriptor_for(
        prepared,
        reference,
        run_id=header.run_id,
        registration_sha256=header.registration_sha256,
        owner_id=header.owner_id,
    )
    if observed != raw or header != expected:
        raise ValueError("Planning complete body/request/context differs from its descriptor")
    return prepared
