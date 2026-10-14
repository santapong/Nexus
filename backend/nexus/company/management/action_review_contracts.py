"""Exact native action review is distinct from approval or an effect permit."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import ManagementContract
from nexus.company.management.owner_view_contracts import ApprovalView
from nexus.harness.canonical import action_hash


class ExactActionDetail(ManagementContract):
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    proposal_sha256: str
    proposal: ActionProposal

    @model_validator(mode="after")
    def exact_native_scope(self) -> ExactActionDetail:
        if (self.company_id, self.task_id, self.trace_id, self.proposal_sha256) != (
            self.proposal.company_id,
            self.proposal.task_id,
            self.proposal.trace_id,
            action_hash(self.proposal),
        ):
            raise ValueError("Action detail differs from its exact native proposal")
        return self


class ActionReview(ManagementContract):
    observed_at: AwareDatetime
    audit: ApprovalView
    availability: Literal["available", "unavailable"]
    detail: ExactActionDetail | None

    @model_validator(mode="after")
    def no_blind_approval(self) -> ActionReview:
        if self.audit.company_id != self.company_id or (
            (self.detail is not None) != (self.availability == "available")
        ):
            raise ValueError("Review availability cannot imply undisclosed action details")
        if self.detail is not None and (
            self.detail.company_id,
            self.detail.proposal_sha256,
            self.detail.proposal.action_id,
        ) != (
            self.company_id,
            self.audit.proposal_sha256,
            self.audit.action_id,
        ):
            raise ValueError("Action review binds another audit proposal")
        return self
