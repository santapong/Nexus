"""Exact typed JSON and human-export bytes; no receipt, publication or action is issued."""

from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from nexus.company.brain.blob_store import validate_utf8
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.cycle_artifacts.common import LIMITATIONS, MAX_BYTES, CycleKind, digest
from nexus.company.cycle_artifacts.contracts import CycleArtifactBasis, checked_basis
from nexus.company.cycle_artifacts.payloads import (
    ANSWERS,
    FACTS,
    STEPS,
    PresentationBrief,
    SupportDraft,
)
from nexus.company.cycle_artifacts.renderers import presentation_html, support_markdown
from nexus.company.management.base import ManagementContract, ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256


class CycleOutputPart(ValueContract):
    part: Literal["json", "html", "markdown"]
    artifact: ArtifactRevisionRef


class CycleOutputManifest(ManagementContract):
    """Pending exact output identities, never actual stored artifacts or receipt evidence."""

    artifact_kind: CycleKind
    action_id: UUID
    recipe_version: str
    parts: tuple[CycleOutputPart, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def closed_parts(self) -> Self:
        require_company(self.company_id, *(row.artifact for row in self.parts))
        expected = ("json", "html" if self.artifact_kind == "presentation" else "markdown")
        if (
            tuple(row.part for row in self.parts) != expected
            or self.recipe_version != f"stockflow-{self.artifact_kind}-v1"
            or len({row.artifact.artifact_revision_id for row in self.parts}) != 2
        ):
            raise ValueError("Cycle two-output manifest kind/parts/recipe differs")
        for row in self.parts:
            key = uuid5(
                self.company_id,
                f"cycle-deliverable:{self.artifact_kind}:{self.action_id}:{row.part}",
            )
            if (
                row.artifact.artifact_id,
                row.artifact.artifact_revision_id,
                row.artifact.revision,
            ) != (key, uuid5(key, "revision:v1"), f"stockflow-{self.artifact_kind}-{row.part}-v1"):
                raise ValueError(
                    "Cycle output reference differs from its exact kind/action namespace"
                )
        return self


class PreparedCycleDeliverable(ValueContract):
    basis: CycleArtifactBasis
    action_id: UUID
    typed_json: bytes = Field(min_length=1, max_length=MAX_BYTES)
    human_export: bytes = Field(min_length=1, max_length=MAX_BYTES)
    manifest: CycleOutputManifest

    @model_validator(mode="after")
    def exact_bytes(self) -> Self:
        basis = checked_basis(self.basis)
        first, second = _content(basis)
        if (
            self.typed_json != first
            or self.human_export != second
            or self.manifest != _manifest(basis, self.action_id, first, second)
        ):
            raise ValueError(
                "Prepared cycle deliverable differs from original basis and exact exports"
            )
        outputs = {row.artifact.artifact_id for row in self.manifest.parts}
        if any(row.artifact_id in outputs for row in basis.inputs.artifacts):
            raise ValueError("Cycle deliverable cannot refer to its own future outputs")
        return self

    @property
    def output_manifest_sha256(self) -> str:
        return canonical_sha256(self.manifest)


def prepare_presentation(basis: CycleArtifactBasis, action_id: UUID) -> PreparedCycleDeliverable:
    return _prepare(basis, action_id, "presentation")


def prepare_support(basis: CycleArtifactBasis, action_id: UUID) -> PreparedCycleDeliverable:
    return _prepare(basis, action_id, "support")


def _prepare(
    basis: CycleArtifactBasis, action_id: UUID, kind: CycleKind
) -> PreparedCycleDeliverable:
    basis = checked_basis(basis)
    if basis.artifact_kind != kind:
        raise ValueError("Cycle producer cannot change the supplied original kind")
    first, second = _content(basis)
    return PreparedCycleDeliverable(
        basis=basis,
        action_id=action_id,
        typed_json=first,
        human_export=second,
        manifest=_manifest(basis, action_id, first, second),
    )


def _content(basis: CycleArtifactBasis) -> tuple[bytes, bytes]:
    if basis.artifact_kind == "presentation":
        value = PresentationBrief(
            company_id=basis.company_id,
            basis=basis,
            fact_ids=FACTS,
            proposed_demo_steps=STEPS,
            limitations=LIMITATIONS,
        )
        raw = value.model_dump_json().encode()
        human = presentation_html(value, digest(raw))
    else:
        draft = SupportDraft(
            company_id=basis.company_id, basis=basis, answer_ids=ANSWERS, limitations=LIMITATIONS
        )
        raw = draft.model_dump_json().encode()
        human = support_markdown(draft, digest(raw))
    validate_utf8(raw, max_bytes=MAX_BYTES)
    validate_utf8(human, max_bytes=MAX_BYTES)
    return raw, human


def _manifest(
    basis: CycleArtifactBasis, action_id: UUID, first: bytes, second: bytes
) -> CycleOutputManifest:
    human: Literal["html", "markdown"] = (
        "html" if basis.artifact_kind == "presentation" else "markdown"
    )
    parts = []
    rows: tuple[tuple[Literal["json", "html", "markdown"], bytes], ...] = (
        ("json", first),
        (human, second),
    )
    for name, raw in rows:
        key = uuid5(basis.company_id, f"cycle-deliverable:{basis.artifact_kind}:{action_id}:{name}")
        parts.append(
            CycleOutputPart(
                part=name,
                artifact=ArtifactRevisionRef(
                    company_id=basis.company_id,
                    artifact_id=key,
                    artifact_revision_id=uuid5(key, "revision:v1"),
                    revision=f"stockflow-{basis.artifact_kind}-{name}-v1",
                    sha256=digest(raw),
                    byte_length=len(raw),
                ),
            )
        )
    return CycleOutputManifest(
        company_id=basis.company_id,
        artifact_kind=basis.artifact_kind,
        action_id=action_id,
        recipe_version=f"stockflow-{basis.artifact_kind}-v1",
        parts=tuple(parts),
    )
