"""Bounded model-authored planning content, separate from server authority and formal plans."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from nexus.company.brain.base import SHA256, ValueContract
from nexus.company.brain.context import ContextManifest
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.core.llm.company_adapter_contracts import JsonSchemaDocument
from nexus.harness.model_client_contracts import GovernedModelResult

TaskKey = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
Title = Annotated[str, Field(min_length=1, max_length=256)]
Description = Annotated[str, Field(min_length=1, max_length=4096)]
Statement = Annotated[str, Field(min_length=1, max_length=1024)]


def _text(value: str, limit: int) -> str:
    if not value.strip() or len(value.encode("utf-8")) > limit:
        raise ValueError("Planning text is blank or exceeds its UTF-8 byte bound")
    return value


class PlanningTask(ValueContract):
    key: TaskKey
    title: Title
    description: Description
    acceptance: tuple[Statement, ...] = Field(min_length=1, max_length=16)
    depends_on: tuple[TaskKey, ...] = Field(max_length=16)
    evidence_ids: tuple[UUID, ...] = Field(max_length=20)

    @field_validator("title")
    @classmethod
    def bounded_title(cls, value: str) -> str:
        return _text(value, 256)

    @field_validator("description")
    @classmethod
    def bounded_description(cls, value: str) -> str:
        return _text(value, 4096)

    @field_validator("acceptance")
    @classmethod
    def bounded_acceptance(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_text(item, 1024) for item in value)

    @model_validator(mode="after")
    def distinct_content(self) -> Self:
        for items in (self.acceptance, self.depends_on, self.evidence_ids):
            if len(set(items)) != len(items):
                raise ValueError("Planning task entries must be unique")
        return self


class PlanningContent(ValueContract):
    tasks: tuple[PlanningTask, ...] = Field(min_length=1, max_length=16)
    questions: tuple[Statement, ...] = Field(max_length=16)

    @field_validator("questions")
    @classmethod
    def bounded_questions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Planning questions must be unique")
        return tuple(_text(item, 1024) for item in value)

    @model_validator(mode="after")
    def bounded_graph(self) -> Self:
        if len(self.model_dump_json().encode("utf-8")) > 65_536:
            raise ValueError("Complete planning content exceeds its byte bound")
        nodes = {task.key for task in self.tasks}
        if len(nodes) != len(self.tasks):
            raise ValueError("Planning task keys must be unique")
        pending = {task.key: set(task.depends_on) for task in self.tasks}
        if any(
            key in dependencies or not dependencies <= nodes
            for key, dependencies in pending.items()
        ):
            raise ValueError("Planning dependencies must name other declared tasks")
        while pending:
            ready = {key for key, dependencies in pending.items() if not dependencies}
            if not ready:
                raise ValueError("Planning dependencies form a cycle")
            pending = {key: value - ready for key, value in pending.items() if key not in ready}
        return self

    def require_evidence(self, allowed: tuple[UUID, ...]) -> None:
        """Model citations may select only actual server-assembled context inclusions."""
        if any(not set(task.evidence_ids) <= set(allowed) for task in self.tasks):
            raise ValueError("Planning content cites evidence absent from its context")


def planning_schema(
    binding: PlanningBinding | None = None, *, manifest: ContextManifest | None = None
) -> JsonSchemaDocument:
    """Closed content schema, optionally bound to exact server refs before approval.

    The bounded annotation contains data only and enters the approved request hash.
    Actual vendor acceptance of this schema remains separate from SDK mock checks.
    """
    document = PlanningContent.model_json_schema()
    if binding is not None:
        binding = PlanningBinding.model_validate_json(binding.model_dump_json())
        if manifest is None or canonical_sha256(manifest) != binding.context_manifest_sha256:
            raise ValueError("Planning v2 requires its complete exact original context manifest")
        manifest = ContextManifest.model_validate_json(manifest.model_dump_json())
        document["$comment"] = json.dumps(
            {
                "version": "nexus.company.planning-binding.v2",
                "binding": binding.model_dump(mode="json"),
                "sha256": canonical_sha256(binding),
                "context_manifest": manifest.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    return JsonSchemaDocument(schema_json=json.dumps(document))


def planning_annotation(schema: JsonSchemaDocument) -> tuple[PlanningBinding, ContextManifest]:
    """V1 stays historical; only complete v2 inputs can support formal provenance."""
    annotation = json.loads(json.loads(schema.document).get("$comment", "{}"))
    if (
        not isinstance(annotation, dict)
        or set(annotation) != {"version", "binding", "sha256", "context_manifest"}
        or annotation["version"] != "nexus.company.planning-binding.v2"
    ):
        raise ValueError("Planning origin requires a complete v2 server annotation")
    binding = PlanningBinding.model_validate_json(json.dumps(annotation["binding"]))
    manifest = ContextManifest.model_validate_json(json.dumps(annotation["context_manifest"]))
    if annotation["sha256"] != canonical_sha256(binding) or schema != planning_schema(
        binding, manifest=manifest
    ):
        raise ValueError("Planning annotation/schema/hash differs from its exact inputs")
    return binding, manifest


class PlanningBinding(ValueContract):
    """Server-captured issuance inputs; later formal publication must perform fresh CAS."""

    goal: GoalRevisionRef
    plan_id: UUID
    expected_plan_revision_id: UUID | None
    context_manifest_sha256: SHA256


class PlanningCandidate(ValueContract):
    """Historical content under frozen references, never an approved/current formal plan."""

    status: Literal["historical_candidate"] = "historical_candidate"
    binding: PlanningBinding
    request_id: UUID
    action_id: UUID
    request_sha256: SHA256
    action_proposal_sha256: SHA256
    content: PlanningContent
    artifact: ArtifactRef
    receipt_id: UUID


PlanningDenial = Literal[
    "model_outcome", "evidence_unavailable", "evidence_mismatch", "invalid_content"
]


class PlanningAttempt(ValueContract):
    governed: GovernedModelResult
    candidate: PlanningCandidate | None
    denial: PlanningDenial | None
    stop_required: bool = True
    company_completed: Literal[False] = False

    @model_validator(mode="after")
    def descriptive_result(self) -> Self:
        if (self.candidate is None) != (self.denial is not None):
            raise ValueError("A rejected planning attempt cannot carry a content candidate")
        if self.stop_required != (self.candidate is None or self.governed.stop_required):
            raise ValueError(
                "A denied planning interpretation must stop without changing native billing"
            )
        if self.candidate is not None:
            recorded = self.governed.recorded
            if (
                recorded is None
                or self.governed.stop_required
                or self.governed.provider_result.status != "response"
                or self.governed.release_status != "released"
                or recorded.billing != "known"
                or recorded.stop_required
                or recorded.receipt_id != self.candidate.receipt_id
                or recorded.artifact != self.candidate.artifact
                or self.governed.provider_result.request_id != self.candidate.request_id
            ):
                raise ValueError("Planning candidate lacks known recorded released provenance")
        return self
