"""Acceptance-bearing work items and validated plan dependency graphs."""

from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import Field, PositiveInt, model_validator

from nexus.company.contracts.base import USD, Contract, Name


class WorkItem(Contract):
    """One logical work identity, retained across retries and execution segments."""

    task_id: UUID
    trace_id: UUID
    goal_id: UUID
    department: Name
    title: Name
    acceptance: tuple[Name, ...] = Field(min_length=1)
    depends_on: tuple[UUID, ...] = ()
    budget_usd: USD = Decimal("1.00")

    @model_validator(mode="after")
    def valid_dependencies(self) -> Self:
        """Reject self-dependencies and duplicate prerequisite identities."""
        if self.task_id in self.depends_on or len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Work dependencies must be unique and exclude the work itself")
        return self


class WorkPlan(Contract):
    """A non-empty company/goal-bound DAG frozen at one plan revision."""

    plan_id: UUID
    goal_id: UUID
    revision: PositiveInt
    items: tuple[WorkItem, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid_graph(self) -> Self:
        """Reject duplicate, foreign, unknown or cyclic work dependencies."""
        nodes = {item.task_id: item for item in self.items}
        if len(nodes) != len(self.items):
            raise ValueError("Work identities must be unique")
        if any(
            item.company_id != self.company_id or item.goal_id != self.goal_id
            for item in self.items
        ):
            raise ValueError("Every item must belong to this company and goal")
        pending = {key: set(item.depends_on) for key, item in nodes.items()}
        if any(not dependencies <= nodes.keys() for dependencies in pending.values()):
            raise ValueError("Unknown work dependency")
        while pending:
            ready = {key for key, dependencies in pending.items() if not dependencies}
            if not ready:
                raise ValueError("Work dependency graph contains a cycle")
            pending = {
                key: dependencies - ready
                for key, dependencies in pending.items()
                if key not in ready
            }
        return self
