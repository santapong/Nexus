"""Portable offline worker results and addressable issued-result envelopes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from nexus.company.contracts.base import Contract, Name


class OfflineOutput(Contract):
    """Saved result of an already-issued deterministic offline model/tool operation."""

    action_id: UUID
    task_id: UUID
    trace_id: UUID
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool: Literal["fake.internal.read.v1", "fake.internal.draft.v1"]
    tool_version: Literal["v1"]
    output: str = Field(min_length=1, max_length=16_384)
    model_requests: Literal[0, 1]
    tool_attempts: Literal[1]
    recorded_at: AwareDatetime

    def require_binding(
        self, company_id: UUID, task_id: UUID, trace_id: UUID, action_id: UUID, digest: str
    ) -> None:
        """A saved artifact never authorizes or changes its exact committed effect identity."""
        if (self.company_id, self.task_id, self.trace_id, self.action_id, self.proposal_hash) != (
            company_id,
            task_id,
            trace_id,
            action_id,
            digest,
        ):
            raise ValueError("Saved offline output differs from the committed effect")


class WorkerResult(Contract):
    """SDK workflow completion is separate from company/business acceptance."""

    task_id: UUID
    action_id: UUID
    segment_id: UUID
    status: Literal["verifying", "outcome_unknown", "blocked"]
    receipt_id: UUID | None = None
    limitations: tuple[Name, ...]
