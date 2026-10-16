"""Path-free selectors for recorded planning provenance; none confer plan authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from nexus.company.management.base import SHA256, ManagementContract, Symbol
from nexus.company.management.goals import GoalRevisionRef


class PlanningOriginRef(ManagementContract):
    kind: Literal["registered-planning.v2"] = "registered-planning.v2"
    goal: GoalRevisionRef
    source_plan_id: UUID
    source_plan_revision_id: UUID
    task_id: UUID
    action_id: UUID
    request_id: UUID
    receipt_id: UUID
    artifact_id: UUID
    artifact_sha256: SHA256
    request_sha256: SHA256
    context_manifest_sha256: SHA256
    content_sha256: SHA256
    mapping_revision: Symbol
    mapping_sha256: SHA256

    @model_validator(mode="after")
    def same_company(self) -> Self:
        if self.goal.company_id != self.company_id:
            raise ValueError("Planning origin goal belongs to another company")
        return self
