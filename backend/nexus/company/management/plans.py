"""One non-executing goal allowance root and fully bound owner plan declarations."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator, model_validator

from nexus.company.brain.base import exact_flag
from nexus.company.contracts.work import WorkPlan
from nexus.company.management.base import (
    SHA256,
    ExactUSD,
    ManagementContract,
    Name,
    RevisionRef,
    Symbol,
    require_company,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.plan_choice_contracts import StrategySelectionRef
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.execution.runtime_contracts import AttemptQuota


class RunBinding(ManagementContract):
    workspace_id: UUID
    actor_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    workflow_name: Name
    workflow_version: Name
    model_profile: Name
    model_registry_version: Name


class ProcedureRoot(ManagementContract):
    procedure_id: UUID
    goal_id: UUID
    binding: RunBinding
    allocation_usd: ExactUSD
    quota: AttemptQuota
    non_executing: Annotated[Literal[True], BeforeValidator(exact_flag)] = True

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.binding)
        return self


class ChildAllocation(ManagementContract):
    binding: RunBinding
    charter: CharterRevisionRef
    allocation_usd: ExactUSD
    quota: AttemptQuota

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.binding, self.charter)
        return self


class VerificationIntent(ManagementContract):
    """Static trigger edge; no imaginary receipt/hash and no accepted-dependency shortcut."""

    author_task_id: UUID
    verifier_task_id: UUID
    check_recipe: Symbol


class PlanPayload(ManagementContract):
    plan: WorkPlan
    goal: GoalRevisionRef
    mandate: RevisionRef
    charters: tuple[CharterRevisionRef, ...] = Field(min_length=1, max_length=32)
    procedure: ProcedureRoot
    children: tuple[ChildAllocation, ...] = Field(min_length=1, max_length=100)
    verification: tuple[VerificationIntent, ...] = Field(default=(), max_length=100)
    strategy_selection: StrategySelectionRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    planning_origin: PlanningOriginRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    coding_admission_sha256: SHA256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("plan", mode="before")
    @classmethod
    def exact_revision(cls, value: object) -> object:
        if isinstance(value, dict) and type(value.get("revision")) is not int:
            raise ValueError("A raw plan revision must be an exact integer")
        return value

    @model_validator(mode="after")
    def partition_and_graph(self) -> Self:
        if (self.procedure.binding.workflow_name == "nexus.coding-cycle.v1") != (
            self.coding_admission_sha256 is not None
        ):
            raise ValueError(
                "Coding procedure metadata cannot be omitted or applied to ordinary plans"
            )
        if self.planning_origin is not None and self.planning_origin.goal != self.goal:
            raise ValueError("Planning origin must retain this exact measured goal")
        require_company(
            self.company_id,
            self.plan,
            self.goal,
            self.mandate,
            self.procedure,
            self.strategy_selection,
            self.planning_origin,
            *self.charters,
            *self.children,
            *self.verification,
        )
        if len({ref.revision_id for ref in self.charters}) != len(self.charters):
            raise ValueError("Charter revisions must be distinct and exact")
        if any(child.charter not in self.charters for child in self.children):
            raise ValueError("Every child must select an exact declared charter revision")
        allocations = _partition(self)
        _acyclic(self, allocations)
        return self


def _partition(payload: PlanPayload) -> dict[UUID, ChildAllocation]:
    if (
        payload.goal.goal_id != payload.plan.goal_id
        or payload.procedure.goal_id != payload.goal.goal_id
    ):
        raise ValueError("Approved plan must retain its measured goal and procedure root")
    nodes = {row.task_id: row for row in payload.plan.items}
    allocations = {row.binding.task_id: row for row in payload.children}
    if len(allocations) != len(payload.children) or allocations.keys() != nodes.keys():
        raise ValueError("Every planned work item requires exactly one child allocation")
    if payload.procedure.binding.task_id in nodes:
        raise ValueError("A procedure allowance root is not executable plan work")
    for task_id, row in nodes.items():
        allocated = allocations[task_id]
        if row.trace_id != allocated.binding.trace_id or row.budget_usd != allocated.allocation_usd:
            raise ValueError("Declared work trace/USD must equal its stable allocation")
        if allocated.binding.workspace_id != payload.procedure.binding.workspace_id:
            raise ValueError("Work bindings must use the procedure workspace")
        if len(row.acceptance) > 32 or len(set(row.acceptance)) != len(row.acceptance):
            raise ValueError("Work acceptance identities must be bounded and unique")
    if sum(row.allocation_usd for row in payload.children) > payload.procedure.allocation_usd:
        raise ValueError("Child USD declarations exceed the one procedure allowance")
    for kind in AttemptQuota.model_fields:
        if sum(getattr(row.quota, kind) for row in payload.children) > getattr(
            payload.procedure.quota, kind
        ):
            raise ValueError("Child quota declarations exceed the one procedure allowance")
    return allocations


def _acyclic(payload: PlanPayload, allocations: dict[UUID, ChildAllocation]) -> None:
    pending = {row.task_id: set(row.depends_on) for row in payload.plan.items}
    if len({edge.verifier_task_id for edge in payload.verification}) != len(payload.verification):
        raise ValueError("Each verifier task has one exact author/check trigger")
    for edge in payload.verification:
        if edge.author_task_id not in pending or edge.verifier_task_id not in pending:
            raise ValueError("Verification trigger references unknown planned work")
        if (
            allocations[edge.author_task_id].binding.actor_id
            == allocations[edge.verifier_task_id].binding.actor_id
        ):
            raise ValueError("A declared verifier must be distinct from its author")
        pending[edge.verifier_task_id].add(edge.author_task_id)
    while pending:
        ready = {task_id for task_id, dependencies in pending.items() if not dependencies}
        if not ready:
            raise ValueError("Dependencies and verification triggers form a cycle")
        pending = {
            key: dependencies - ready for key, dependencies in pending.items() if key not in ready
        }
