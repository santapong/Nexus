"""Closed cycle descriptions; no credential, current proof or execution authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.contracts.work import WorkItem
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    RevisionRef,
    ValueContract,
    require_company,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.plans import ChildAllocation, ProcedureRoot, VerificationIntent
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission

CycleRole = Literal[
    "strategy",
    "strategy_check",
    "engineering",
    "engineering_check",
    "presentation",
    "presentation_check",
    "support",
    "support_check",
    "report",
    "report_check",
    "sender",
]
CycleStage = Literal["strategy", "full"]
CYCLE_ROLES: tuple[CycleRole, ...] = (
    "strategy",
    "strategy_check",
    "engineering",
    "engineering_check",
    "presentation",
    "presentation_check",
    "support",
    "support_check",
    "report",
    "report_check",
    "sender",
)


def require_exact_cycle_quota(quota: AttemptQuota) -> None:
    """Reject copied bool/float/string counts before a serializer sees their values."""
    AttemptQuota.model_validate({name: getattr(quota, name) for name in AttemptQuota.model_fields})


class StockFlowCycleSlot(ValueContract):
    """One fixed role/work/allocation/tool/edge description in trusted configuration."""

    role: CycleRole
    child: ChildAllocation
    work: WorkItem
    tool: ToolPermission
    verification: VerificationIntent | None = None

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(
            self.child.company_id,
            self.child.binding,
            self.child.charter,
            self.work,
            self.verification,
        )
        require_exact_cycle_quota(self.child.quota)
        if (self.child.binding.task_id, self.child.binding.trace_id, self.child.allocation_usd) != (
            self.work.task_id,
            self.work.trace_id,
            self.work.budget_usd,
        ):
            raise ValueError("Cycle slot work and permanent allocation differ")
        return self


class StockFlowCycleAdmission(ManagementContract):
    """Operator-configured finite layout, separate from actual owner/native admission."""

    goal: GoalRevisionRef
    mandate: RevisionRef
    plan_id: UUID
    registry_revision: Name
    registry_sha256: SHA256
    procedure: ProcedureRoot
    slots: tuple[StockFlowCycleSlot, ...] = Field(min_length=11, max_length=11)

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        require_company(
            self.company_id,
            self.goal,
            self.mandate,
            self.procedure,
            *(row.child for row in self.slots),
            *(row.work for row in self.slots),
        )
        require_exact_cycle_quota(self.procedure.quota)
        if tuple(row.role for row in self.slots) != CYCLE_ROLES:
            raise ValueError("Cycle roles must be complete, unique and canonically ordered")
        if self.procedure.goal_id != self.goal.goal_id:
            raise ValueError("Cycle procedure binds another goal")
        for field in ("task_id", "trace_id", "run_id"):
            values = tuple(getattr(row.child.binding, field) for row in self.slots)
            if len(set(values)) != len(values) or getattr(self.procedure.binding, field) in values:
                raise ValueError("Cycle children/root require distinct permanent work identities")
        if any(
            row.work.goal_id != self.goal.goal_id
            or row.child.binding.workspace_id != self.procedure.binding.workspace_id
            for row in self.slots
        ):
            raise ValueError("Cycle child escapes its goal or workspace")
        return self


class StockFlowCycleSelection(ValueContract):
    """Matched descriptions only; no approval, readiness, lease, receipt or permit."""

    stage: CycleStage
    goal_id: UUID
    plan_id: UUID
    procedure_id: UUID
    task_ids: tuple[UUID, ...] = Field(min_length=2, max_length=11)
    native_task_ids: tuple[UUID, ...] = Field(max_length=2)
    sender_task_id: UUID | None
