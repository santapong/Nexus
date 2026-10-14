"""Strict actual native state/read selectors; serialization carries no caller authority."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_serializer, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import Flag
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.base import (
    SHA256,
    ExactUSD,
    ManagementContract,
    SourceTime,
    Symbol,
    require_company,
)
from nexus.company.management.cancellation_contracts import InheritedCancellation
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operations import Eligibility, LedgerUSD
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.harness.journal_contracts import ActionRecord


class DecisionSelector(ManagementContract):
    kind: Literal["decision_required"] = "decision_required"
    action_id: UUID


class BlockedSelector(ManagementContract):
    kind: Literal["work_blocked"] = "work_blocked"
    task_id: UUID


class CapSelector(ManagementContract):
    kind: Literal["cap_exhausted"] = "cap_exhausted"
    task_id: UUID | None = None


class FailedReceiptSelector(ManagementContract):
    kind: Literal["receipt_recorded"] = "receipt_recorded"
    action_id: UUID


class DigestSelector(ManagementContract):
    kind: Literal["digest_due"] = "digest_due"
    schedule: Symbol


NativeEventSelector = Annotated[
    DecisionSelector | BlockedSelector | CapSelector | FailedReceiptSelector | DigestSelector,
    Field(discriminator="kind"),
]


class DecisionState(ManagementContract):
    kind: Literal["decision_required"] = "decision_required"
    action: ActionRecord
    work: RunBinding
    registration_sha256: SHA256
    plan: PlanRevisionRef
    policy_version: Symbol
    price_version: Symbol

    @model_validator(mode="after")
    def exact_work(self) -> Self:
        require_company(self.company_id, self.action, self.action.proposal, self.work, self.plan)
        proposed = self.action.proposal
        if (
            (proposed.task_id, proposed.trace_id, proposed.actor_id)
            != (self.work.task_id, self.work.trace_id, self.work.actor_id)
            or self.action.approval is not None
            or self.action.state.value != "awaiting_approval"
        ):
            raise ValueError("Decision state requires its exact native pending work/action")
        if (proposed.policy_version, proposed.price_version) != (
            self.policy_version,
            self.price_version,
        ):
            raise ValueError("Pending decision policy/prices are no longer current")
        return self


class BlockedState(ManagementContract):
    kind: Literal["work_blocked"] = "work_blocked"
    work: RunBinding
    registration_sha256: SHA256
    execution: ExecutionSnapshot
    eligibility: Eligibility
    cancellation: InheritedCancellation | None = None

    @model_validator(mode="after")
    def exact_work(self) -> Self:
        require_company(
            self.company_id, self.work, self.execution, self.eligibility, self.cancellation
        )
        if self.eligibility.state not in {"blocked", "cancelled"} or (
            self.execution.registration.work.task_id,
            self.execution.registration.run_id,
            self.execution.actor_id,
            self.execution.workspace_id,
        ) != (self.work.task_id, self.work.run_id, self.work.actor_id, self.work.workspace_id):
            raise ValueError("Blocked state requires its exact native execution/binding")
        if (self.eligibility.state == "cancelled") != (self.cancellation is not None):
            raise ValueError("Explicit cancellation is distinct from an inactive/blocked state")
        if (
            self.eligibility.work != self.work
            or self.execution.registration.work.trace_id != self.work.trace_id
        ):
            raise ValueError("Blocked eligibility and actual trace must match their native work")
        if (
            self.cancellation is not None
            and self.cancellation.requested_task_id != self.work.task_id
        ):
            raise ValueError("Cancellation query must retain the exact requested native task")
        return self


class CompanyCapState(ManagementContract):
    kind: Literal["company_cap"] = "company_cap"
    budget_day: date
    cap_usd: ExactUSD
    held_usd: LedgerUSD
    spent_usd: LedgerUSD
    billing_unknown: Flag
    policy_version: Symbol

    @field_serializer("budget_day")
    def exact_day(self, value: date) -> str:
        """The native SQL DATE keeps its exact ISO date in the canonical JSON state recipe."""
        return value.isoformat()

    @model_validator(mode="after")
    def exhausted(self) -> Self:
        if self.held_usd + self.spent_usd < self.cap_usd:
            raise ValueError("Native company cap is not exhausted")
        return self


class WorkCapState(ManagementContract):
    kind: Literal["work_cap"] = "work_cap"
    work: RunBinding
    root_task_id: UUID
    allocation_usd: ExactUSD
    cap_usd: ExactUSD
    delegated_usd: LedgerUSD
    held_usd: LedgerUSD
    spent_usd: LedgerUSD
    billing_unknown: Flag
    policy_version: Symbol

    @model_validator(mode="after")
    def own_slice(self) -> Self:
        require_company(self.company_id, self.work)
        if (
            self.cap_usd > self.allocation_usd
            or self.delegated_usd > self.allocation_usd
            or (self.held_usd + self.spent_usd + self.delegated_usd < self.cap_usd)
        ):
            raise ValueError("Native work cap requires its exhausted permanent own slice")
        return self


class RegisteredDigestPolicy(ManagementContract):
    """Explicit server-saved schedule/report/policy; event bodies cannot select a clock."""

    schedule: Symbol
    kind: Literal["daily", "weekly"]
    report_id: UUID
    policy: NotificationPolicy
    resource: ResourceRef
    registered_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def exact_registration(self) -> Self:
        require_company(self.company_id, self.resource)
        if self.expires_at <= self.registered_at:
            raise ValueError("Digest registration requires its actual finite deadline")
        return self


class DigestState(ManagementContract):
    kind: Literal["digest_due"] = "digest_due"
    saved: SavedOperatingReport
    registration: RegisteredDigestPolicy
    due_bucket: Symbol
    scheduled_for: AwareDatetime

    @model_validator(mode="after")
    def exact_saved(self) -> Self:
        require_company(self.company_id, self.saved, self.registration)
        if self.saved.report_id != self.registration.report_id:
            raise ValueError("Digest state must retain its registered owner report")
        return self


NativeEventState = (
    DecisionState | BlockedState | CompanyCapState | WorkCapState | DigestState | ActionReceipt
)


class NativeFactProjection(ManagementContract):
    """Resolved/recomputed native facts + independent privacy/deadlines, never an effect permit."""

    selector: NativeEventSelector
    state: NativeEventState
    resource: ResourceRef
    required_resource_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    artifacts: tuple[ArtifactRevisionRef, ...] = Field(default=(), max_length=33)
    protection_deadlines: tuple[AwareDatetime, ...] = Field(default=(), max_length=128)
    source_recorded_at: AwareDatetime

    @model_validator(mode="after")
    def scoped(self) -> Self:
        require_company(self.company_id, self.selector, self.state, self.resource, *self.artifacts)
        if self.resource.resource_id not in self.required_resource_ids:
            raise ValueError(
                "Native event subject resource must remain in the complete input scope"
            )
        if len(set(self.required_resource_ids)) != len(self.required_resource_ids) or len(
            {row.artifact_revision_id for row in self.artifacts}
        ) != len(self.artifacts):
            raise ValueError("Native fact resource/artifact input scope must be unique")
        kinds = {
            DecisionState: "decision_required",
            BlockedState: "work_blocked",
            CompanyCapState: "cap_exhausted",
            WorkCapState: "cap_exhausted",
            DigestState: "digest_due",
            ActionReceipt: "receipt_recorded",
        }
        if kinds[type(self.state)] != self.selector.kind:
            raise ValueError("Native fact selector/state kind differs")
        return self

    @property
    def state_sha256(self) -> str:
        """Integrity hash of actual resolved state; the reader must still qualify its provenance."""
        return canonical_sha256(self.state)

    @property
    def source_event(self) -> SourceTime:
        """Retain native date precision; observation time cannot invent an occurrence instant."""
        if isinstance(self.state, CompanyCapState):
            return SourceTime(
                precision="day",
                value=self.state.budget_day.isoformat(),
                basis="Native Bangkok DailyBudget day; observation time is separate",
            )
        if isinstance(self.state, (ActionReceipt, DigestState)):
            stamp = (
                self.state.recorded_at
                if isinstance(self.state, ActionReceipt)
                else self.state.saved.observed_at
            )
            return SourceTime(
                precision="instant",
                value=stamp.isoformat(),
                basis="Native immutable receipt/report recorded observation",
            )
        return SourceTime(
            precision="unknown",
            value=None,
            basis="Native work/action row has no immutable occurrence timestamp",
        )
