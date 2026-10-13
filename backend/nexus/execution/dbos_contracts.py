"""Portable scheduling identity; persistent counters and authority stay in application tables."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from nexus.company.contracts.base import Contract
from nexus.harness.journal_contracts import LedgerScope


class SegmentCommand(Contract):
    """Server-authored continuation, with no callable, credentials or new budget in its payload."""

    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    workspace_id: UUID
    run_id: UUID
    action_id: UUID
    segment_id: UUID

    @property
    def workflow_id(self) -> str:
        """Bind a permanent scheduling ID to the logical run and segment."""
        return str(
            uuid5(
                NAMESPACE_URL,
                (f"nexus-company:{self.company_id}:{self.task_id}:{self.run_id}:{self.segment_id}"),
            )
        )

    def require_scope(self, scope: LedgerScope) -> None:
        """A continuation cannot replace the authenticated task, trace or actor."""
        if (self.company_id, self.task_id, self.trace_id, self.actor_id) != (
            scope.company_id,
            scope.task_id,
            scope.trace_id,
            scope.principal_id,
        ):
            raise ValueError("Continuation and trusted scope disagree")
