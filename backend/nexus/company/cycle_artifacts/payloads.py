"""Closed authored content kinds; unsupported free claims cannot receive a mechanical pass."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.cycle_artifacts.common import LIMITATIONS
from nexus.company.cycle_artifacts.contracts import CycleArtifactBasis
from nexus.company.management.base import ValueContract

FACTS = ("source_patch_scope", "baseline_checks", "post_checks", "independent_engineering_check")
STEPS = (
    "inspect_nominated_source",
    "review_protected_patch",
    "review_independent_checks",
    "request_owner_decision",
)
ANSWERS = (
    "isolated_check_scope",
    "deployment_unknown",
    "request_version",
    "request_sanitized_reproduction",
    "owner_review",
)


class PresentationBrief(ValueContract):
    schema_version: Literal["nexus.company.presentation-brief.v1"] = (
        "nexus.company.presentation-brief.v1"
    )
    artifact_kind: Literal["presentation"] = "presentation"
    company_id: UUID
    basis: CycleArtifactBasis
    title: Literal["StockFlow CSV engineering review"] = "StockFlow CSV engineering review"
    audience: Literal["internal_review_draft"] = "internal_review_draft"
    fact_ids: tuple[str, ...] = Field(min_length=4, max_length=4)
    proposed_demo_steps: tuple[str, ...] = Field(min_length=4, max_length=4)
    deployment_state: Literal["not_observed"] = "not_observed"
    customer_readiness: Literal["not_assessed"] = "not_assessed"
    behavior_details: Literal["not_observed"] = "not_observed"
    decision_request: Literal["Owner review of the isolated engineering evidence is required."] = (
        "Owner review of the isolated engineering evidence is required."
    )
    limitations: tuple[str, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def closed_content(self) -> Self:
        if (
            self.company_id != self.basis.company_id
            or self.basis.artifact_kind != "presentation"
            or self.fact_ids != FACTS
            or self.proposed_demo_steps != STEPS
            or self.limitations != LIMITATIONS
        ):
            raise ValueError("Presentation supplied scope/facts/steps/limitations differ")
        return self


class SupportDraft(ValueContract):
    schema_version: Literal["nexus.company.support-draft.v1"] = "nexus.company.support-draft.v1"
    artifact_kind: Literal["support"] = "support"
    company_id: UUID
    basis: CycleArtifactBasis
    case_kind: Literal["hypothetical_csv_case"] = "hypothetical_csv_case"
    communication_state: Literal["internal_draft"] = "internal_draft"
    hypothetical_problem: Literal["CSV import behavior differs from expectation."] = (
        "CSV import behavior differs from expectation."
    )
    answer_ids: tuple[str, ...] = Field(min_length=5, max_length=5)
    deployment_state: Literal["not_observed"] = "not_observed"
    customer_readiness: Literal["not_assessed"] = "not_assessed"
    behavior_details: Literal["not_observed"] = "not_observed"
    escalation: Literal[
        "Owner review and the actual deployed version/reproduction are required."
    ] = "Owner review and the actual deployed version/reproduction are required."
    limitations: tuple[str, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def closed_content(self) -> Self:
        if (
            self.company_id != self.basis.company_id
            or self.basis.artifact_kind != "support"
            or self.answer_ids != ANSWERS
            or self.limitations != LIMITATIONS
        ):
            raise ValueError("Support supplied scope/answers/limitations differ")
        return self
