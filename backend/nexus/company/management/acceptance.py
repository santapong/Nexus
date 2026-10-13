"""Exact resolved verifier targets/protected results; declaration alone never completes work."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.base import SHA256, ManagementContract, Name, Symbol, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding


class VerificationSpec(ManagementContract):
    """Resolved only from actual issued results; never a nullable future target."""

    author: RunBinding
    verifier: RunBinding
    action_id: UUID
    proposal_sha256: SHA256
    receipt_id: UUID
    receipt_sha256: SHA256
    work_snapshot_sha256: SHA256  # Exact M1 ExecutionWork.registration_hash, not report context.
    criterion_ids: tuple[Name, ...] = Field(min_length=1, max_length=32)
    artifacts: tuple[ArtifactRevisionRef, ...] = Field(min_length=1, max_length=32)
    check_recipe: Symbol

    @model_validator(mode="after")
    def exact_separation(self) -> Self:
        require_company(self.company_id, self.author, self.verifier, *self.artifacts)
        if (
            self.author.actor_id == self.verifier.actor_id
            or self.author.task_id == self.verifier.task_id
        ):
            raise ValueError("Independent verification requires a distinct actor and work identity")
        if self.author.workspace_id != self.verifier.workspace_id:
            raise ValueError("Author and verifier belong to different workspaces")
        if len(set(self.criterion_ids)) != len(self.criterion_ids):
            raise ValueError("Exact criterion identities must be unique")
        if len({row.artifact_revision_id for row in self.artifacts}) != len(self.artifacts):
            raise ValueError("Exact output artifacts must be unique")
        return self


class ProtectedCheckProof(ManagementContract):
    """A registered mechanical checker/protected result must later validate this reference."""

    proof_id: UUID
    recipe: Symbol
    result_artifact: ArtifactRevisionRef
    target_sha256: SHA256

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.result_artifact)
        return self


class WorkAcceptance(ManagementContract):
    """Trusted publisher read shape, not a raw caller verdict or actual completion permission."""

    acceptance_id: UUID
    target: VerificationSpec
    verdict: Literal["pass", "reject", "inconclusive"]
    proofs: tuple[ProtectedCheckProof, ...] = Field(default=(), max_length=32)
    limitations: tuple[Name, ...] = Field(default=(), max_length=32)
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def protected(self) -> Self:
        require_company(self.company_id, self.target, *self.proofs)
        if self.verdict == "pass" and not self.proofs:
            raise ValueError("Passing acceptance requires registered protected check results")
        expected = canonical_sha256(self.target)
        if any(
            proof.target_sha256 != expected or proof.recipe != self.target.check_recipe
            for proof in self.proofs
        ):
            raise ValueError("Protected check reference binds another target or recipe")
        if len({row.proof_id for row in self.proofs}) != len(self.proofs):
            raise ValueError("Protected proofs must be exact and unique")
        return self


class AcceptanceInvalidation(ManagementContract):
    invalidation_id: UUID
    acceptance_id: UUID
    target_sha256: SHA256
    reason: Literal[
        "source_changed", "criteria_changed", "proof_unavailable", "scope_revoked", "invalid_check"
    ]
    recorded_by: UUID
    recorded_at: AwareDatetime
