"""Engineering worker observations bind actual evidence IDs without granting execution authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.builder.engineering_contracts import ENGINEERING_RECIPE
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.base import ManagementContract, Name, require_company
from nexus.execution.dbos_contracts import SegmentCommand

EngineeringPhase = Literal["author", "verifier"]
EngineeringStatus = Literal[
    "published", "accepted", "reject", "inconclusive", "outcome_unknown", "blocked"
]
EngineeringWorkflow = Literal["engineering.change", "engineering.verify"]


class EngineeringSegmentResult(ManagementContract):
    """Historical segment observation; current acceptance still requires fresh protected reads."""

    command: SegmentCommand
    phase: EngineeringPhase
    workflow_name: EngineeringWorkflow
    workflow_version: Literal["v1"] = "v1"
    status: EngineeringStatus
    receipt_id: UUID | None = None
    acceptance_id: UUID | None = None
    protected_proof: ArtifactRevisionRef | None = None
    billing: Literal["known", "unconfirmed"]
    observed_at: AwareDatetime
    limitations: tuple[Name, ...] = (
        "mechanical_engineering_only",
        "business_readiness_unproven",
    )

    @property
    def workflow_id(self) -> UUID:
        """The same immutable command determines the portable workflow identity."""
        return UUID(self.command.workflow_id)

    @model_validator(mode="after")
    def exact_phase_and_evidence(self) -> Self:
        """DTO decoding checks scope/shape only; no caller status becomes trusted acceptance."""
        require_company(self.company_id, self.command, self.protected_proof)
        expected = "engineering.change" if self.phase == "author" else "engineering.verify"
        if self.workflow_name != expected:
            raise ValueError("Engineering workflow differs from its exact phase")
        proof_status = self.status in {"accepted", "reject", "inconclusive"}
        if proof_status:
            if (
                self.phase != "verifier"
                or self.receipt_id is None
                or self.acceptance_id is None
                or self.protected_proof is None
                or self.protected_proof.revision != ENGINEERING_RECIPE
            ):
                raise ValueError(
                    "Engineering verdict requires the actual verifier receipt and proof"
                )
        elif self.acceptance_id is not None or self.protected_proof is not None:
            raise ValueError("Unaccepted segment cannot carry acceptance authority")
        if self.status == "published" and (self.phase != "author" or self.receipt_id is None):
            raise ValueError("Published engineering author requires its actual receipt")
        return self


def accepted_segment_result(
    command: SegmentCommand,
    receipt: ActionReceipt,
    acceptance: WorkAcceptance,
    *,
    billing: Literal["known", "unconfirmed"],
    observed_at: AwareDatetime,
) -> EngineeringSegmentResult:
    """Trusted adapter builds a descriptive verdict from resolved records, never caller status.

    Caller must resolve current protected authority; this pure binding helper cannot do so.
    """
    require_company(command.company_id, receipt, acceptance)
    verifier = acceptance.target.verifier
    if (
        (receipt.task_id, receipt.trace_id, receipt.action_id, receipt.outcome)
        != (command.task_id, command.trace_id, command.action_id, "succeeded")
        or (
            verifier.task_id,
            verifier.trace_id,
            verifier.run_id,
            verifier.actor_id,
            verifier.workspace_id,
        )
        != (
            command.task_id,
            command.trace_id,
            command.run_id,
            command.actor_id,
            command.workspace_id,
        )
        or (verifier.workflow_name, verifier.workflow_version) != ("engineering.verify", "v1")
        or acceptance.target.check_recipe != ENGINEERING_RECIPE
        or len(acceptance.proofs) != 1
    ):
        raise ValueError("Resolved engineering acceptance differs from the issued verifier segment")
    status = "accepted" if acceptance.verdict == "pass" else acceptance.verdict
    return EngineeringSegmentResult(
        company_id=command.company_id,
        command=command,
        phase="verifier",
        workflow_name="engineering.verify",
        status=status,
        receipt_id=receipt.receipt_id,
        acceptance_id=acceptance.acceptance_id,
        protected_proof=acceptance.proofs[0].result_artifact,
        billing=billing,
        observed_at=observed_at,
        limitations=acceptance.limitations,
    )
