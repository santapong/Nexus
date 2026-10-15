"""Independent supplied-data check descriptions; native acceptance remains unavailable here."""

from typing import Self

from pydantic import Field, model_validator

from nexus.company.cycle_artifacts.common import LIMITATIONS, MAX_BYTES, CycleKind, criteria_for
from nexus.company.cycle_artifacts.contracts import CycleArtifactBasis
from nexus.company.cycle_artifacts.production import CycleOutputManifest
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.base import SHA256, ManagementContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CheckVerdict, CriterionCheckResult
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs


class CycleArtifactCheckInput(ManagementContract):
    artifact_kind: CycleKind
    target: VerificationSpec
    original: CycleArtifactBasis | None
    manifest: CycleOutputManifest
    inputs: GeneratedArtifactInputs
    typed_json: bytes | None = Field(max_length=MAX_BYTES)
    human_export: bytes | None = Field(max_length=MAX_BYTES)

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.target, self.original, self.manifest, self.inputs)
        return self


class CycleArtifactCheckPayload(ManagementContract):
    artifact_kind: CycleKind
    recipe_version: str
    target_sha256: SHA256
    output_manifest_sha256: SHA256
    original_basis_sha256: SHA256 | None
    input_snapshot_sha256: SHA256
    verdict: CheckVerdict
    criteria: tuple[CriterionCheckResult, ...] = Field(min_length=1, max_length=32)
    limitations: tuple[str, ...] = LIMITATIONS


class CycleCheckProductionSnapshot(ManagementContract):
    """Hashable immutable references/basis, excluding supplied raw byte buffers."""

    artifact_kind: CycleKind
    target: VerificationSpec
    original: CycleArtifactBasis | None
    manifest: CycleOutputManifest
    inputs: GeneratedArtifactInputs


def cycle_check_snapshot(command: CycleArtifactCheckInput) -> CycleCheckProductionSnapshot:
    return CycleCheckProductionSnapshot.model_validate(
        command.model_dump(exclude={"typed_json", "human_export"}, warnings=False)
    )


class CycleArtifactCheckResult(CycleArtifactCheckPayload):
    result_sha256: SHA256

    @model_validator(mode="after")
    def truthful_result(self) -> Self:
        names = tuple(row.criterion_id for row in self.criteria)
        verdict = (
            "reject"
            if any(row.verdict == "reject" for row in self.criteria)
            else "inconclusive"
            if any(row.verdict == "inconclusive" for row in self.criteria)
            else "pass"
        )
        expected = CycleArtifactCheckPayload.model_validate(
            self.model_dump(exclude={"result_sha256"})
        )
        if (
            self.limitations != LIMITATIONS
            or self.verdict != verdict
            or self.recipe_version != f"stockflow-{self.artifact_kind}-v1"
            or len(names) != len(set(names))
            or (self.verdict == "pass" and names != criteria_for(self.artifact_kind))
            or self.result_sha256 != canonical_sha256(expected)
        ):
            raise ValueError("Cycle check criteria/aggregate/hash/limitations differ")
        return self
