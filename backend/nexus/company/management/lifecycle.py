"""Immutable owner decisions/admin revision facts cannot be fabricated execution attempts."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    Revision,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import PlanPayload


class PlanRevisionRef(ManagementContract):
    plan_id: UUID
    plan_revision_id: UUID
    revision: Revision
    sha256: SHA256


class PlanRevision(PlanRevisionRef):
    payload: PlanPayload
    proposed_by: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_snapshot(self) -> Self:
        require_company(self.company_id, self.payload)
        if (self.plan_id, self.revision) != (self.payload.plan.plan_id, self.payload.plan.revision):
            raise ValueError("Plan revision identity differs from its exact payload")
        if self.sha256 != canonical_sha256(self.payload):
            raise ValueError("Plan digest differs from its exact payload")
        return self


class OwnerPlanDecision(ManagementContract):
    decision_id: UUID
    plan: PlanRevisionRef
    owner_id: UUID
    kind: Literal["approve", "revoke"]
    reason: Name
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        require_company(self.company_id, self.plan)
        return self


class PlanSnapshot(ManagementContract):
    """Read projection of persisted decisions, never an approval request or activation permit."""

    revision: PlanRevision
    state: Literal["proposed", "approved", "revoked"]
    decision: OwnerPlanDecision | None = None

    @model_validator(mode="after")
    def projected_decision(self) -> Self:
        require_company(self.company_id, self.revision, self.decision)
        if self.state == "proposed":
            if self.decision is not None:
                raise ValueError("A proposed plan has no effective owner decision")
            return self
        if self.decision is None:
            raise ValueError("An operative projection requires its exact immutable owner decision")
        ref = self.decision.plan
        if (ref.plan_id, ref.plan_revision_id, ref.revision, ref.sha256) != (
            self.revision.plan_id,
            self.revision.plan_revision_id,
            self.revision.revision,
            self.revision.sha256,
        ) or self.decision.kind != ("approve" if self.state == "approved" else "revoke"):
            raise ValueError("Owner decision binds another plan revision or lifecycle")
        return self


class AdministrativeRevisionEvent(ManagementContract):
    event_id: UUID
    procedure_id: UUID
    parent_task_id: UUID
    parent_run_id: UUID
    previous_plan: PlanRevisionRef
    next_plan: PlanRevisionRef
    owner_decision_id: UUID
    owner_id: UUID
    revision_counter: Revision
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def revision_use(self) -> Self:
        require_company(self.company_id, self.previous_plan, self.next_plan)
        if self.previous_plan.plan_revision_id == self.next_plan.plan_revision_id:
            raise ValueError("An administrative revision must change the immutable plan snapshot")
        if self.revision_counter > 2:
            raise ValueError("Administrative revisions exceed the lifetime root limit")
        return self
