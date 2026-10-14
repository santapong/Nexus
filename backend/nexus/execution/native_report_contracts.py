"""Native procedure results describe actual receipt/proof facts, never execution permission."""

from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from nexus.company.contracts.base import Contract, Name


class NativeReportResult(Contract):
    """Workflow completion is distinct from accepted work and business readiness."""

    task_id: UUID
    action_id: UUID
    segment_id: UUID
    status: Literal["published", "accepted", "reject", "inconclusive", "outcome_unknown", "blocked"]
    receipt_id: UUID | None = None
    acceptance_id: UUID | None = None
    limitations: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def actual_proof(self) -> Self:
        if self.status in {"accepted", "reject", "inconclusive"} and self.acceptance_id is None:
            raise ValueError("A proof result requires its native acceptance identity")
        if (
            self.status in {"published", "accepted", "reject", "inconclusive"}
            and self.receipt_id is None
        ):
            raise ValueError("Known native output requires its actual issued receipt")
        return self
