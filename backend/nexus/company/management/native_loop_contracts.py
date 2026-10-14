"""Fixed owner-record selectors and bounded native tick observations, never permits."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.base import ManagementContract, Name, require_company
from nexus.company.management.native_profile_contracts import NativeReportProfileRef
from nexus.company.management.scheduling_contracts import ScheduledWork
from nexus.harness.journal_contracts import ActionRecord

LoopState = Literal[
    "not_due",
    "author_pending",
    "author_dispatched",
    "verifier_pending",
    "verifier_dispatched",
    "accepted",
    "blocked",
    "outcome_unknown",
    "closed",
]


def phase_states(phase: Literal["author", "verifier"]) -> tuple[LoopState, LoopState]:
    """Descriptive state names do not replace native action/effect/acceptance facts."""
    return (
        ("author_pending", "author_dispatched")
        if phase == "author"
        else ("verifier_pending", "verifier_dispatched")
    )


class NativeOperatingRegistration(ManagementContract):
    """Trusted server construction fixes one saved occurrence; JSON never authenticates it."""

    registration_id: UUID
    intent: Literal["operate_saved_native_report_v1"] = "operate_saved_native_report_v1"
    profile: NativeReportProfileRef
    fallback_seconds: Literal[60] = 60
    opportunity_seconds: Literal[900] = 900

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.profile)
        return self

    def action_id(self, phase: Literal["author", "verifier"]) -> UUID:
        """Select the preparer's fixed action identity; a derived UUID supplies no authority."""
        return uuid5(self.profile.report_id, f"native-report-profile-v1:{phase}")


class NativeOperatingTick(ManagementContract):
    """Native observations/new preparation or dispatch, without cached execution authority."""

    registration_id: UUID
    observed_at: AwareDatetime
    state: LoopState
    reason: Name
    author_action_id: UUID
    verifier_action_id: UUID
    pending: ActionRecord | None = None
    scheduled: ScheduledWork | None = None
    acceptance: WorkAcceptance | None = None
    historical_acceptance_ids: tuple[UUID, ...] = Field(default=(), max_length=1)
    preparation_performed: bool = Field(default=False, strict=True)
    opportunity_scan: bool = Field(default=False, strict=True)
    next_fallback_at: AwareDatetime
    model_requests: Literal[0] = 0

    @model_validator(mode="after")
    def scoped(self) -> Self:
        for value in (self.pending, self.scheduled, self.acceptance):
            if value is not None:
                require_company(self.company_id, value)
        if (self.state == "accepted") != (self.acceptance is not None):
            raise ValueError("A current accepted observation requires its actual native proof")
        return self
