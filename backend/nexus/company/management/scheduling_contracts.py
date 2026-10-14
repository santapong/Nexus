"""Exact bounded scheduling scans and descriptive queue receipts, never effect permits."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from nexus.company.brain.base import Flag
from nexus.company.management.base import SHA256, ManagementContract, Name, Symbol, ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operations import Eligibility

Sequence = Annotated[int, Field(ge=0, strict=True)]


class EventWake(ValueContract):
    """Exact native sequenced event lookup; caller supplies no content or authority."""

    kind: Literal["event"] = "event"
    stream: Literal["brain", "control"]
    event_id: UUID


class DueWake(ValueContract):
    """Explicit canonical minute bucket; this shape starts no background timer."""

    kind: Literal["due"] = "due"
    bucket: AwareDatetime

    @field_validator("bucket")
    @classmethod
    def exact_minute(cls, value: AwareDatetime) -> AwareDatetime:
        if value.second or value.microsecond:
            raise ValueError("Due buckets must align to an exact aware minute")
        return value


Wake = Annotated[EventWake | DueWake, Field(discriminator="kind")]


class ScanPage(ValueContract):
    """Continuation binds a stable native plan index and both exact trigger ranges."""

    after_task_id: UUID
    brain_sequence: Sequence
    control_sequence: Sequence
    plan_snapshot_sha256: SHA256


class ScanRequest(ManagementContract):
    wake: Wake
    task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    page: ScanPage | None = None

    @model_validator(mode="after")
    def unique_selection(self) -> Self:
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Scheduler task selection must be unique")
        return self


def request_sha256(request: ScanRequest) -> str:
    """Normalize equivalent task sets; preserve exact trigger and page identity."""
    request = ScanRequest.model_validate_json(request.model_dump_json())
    return canonical_sha256(
        request.model_copy(update={"task_ids": tuple(sorted(request.task_ids))})
    )


class WorkflowRegistration(ValueContract):
    """Server registered portable SegmentCommand workflow ABI, never a caller override."""

    workflow_name: Name
    workflow_version: Name
    queue_name: Name
    application_name: Name


class SchedulerPolicy(ValueContract):
    recipe_version: Symbol
    consumer: Symbol = "nexus.management.scheduler"
    max_tasks: Annotated[int, Field(ge=1, le=100, strict=True)] = 100
    workflows: tuple[WorkflowRegistration, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_workflows(self) -> Self:
        keys = {(row.workflow_name, row.workflow_version) for row in self.workflows}
        if len(keys) != len(self.workflows):
            raise ValueError("Scheduler workflow ABIs must be unique")
        return self


class ScheduledWork(ManagementContract):
    """Eligible/queued is descriptive only; fresh M1 execution still owns every effect."""

    eligibility: Eligibility
    action_id: UUID | None = None
    dispatch: Literal["none", "enqueued", "existing"] = "none"
    segment_id: UUID | None = None
    workflow_id: Name | None = None

    @model_validator(mode="after")
    def exact_dispatch(self) -> Self:
        if self.company_id != self.eligibility.company_id:
            raise ValueError("Scheduler work crosses its company")
        if self.dispatch != "none":
            if any(value is None for value in (self.action_id, self.segment_id, self.workflow_id)):
                raise ValueError("A queued work receipt needs its exact action/segment/workflow")
        elif self.segment_id is not None or self.workflow_id is not None:
            raise ValueError("Unqueued work cannot claim a workflow")
        return self


class ScanReceipt(ManagementContract):
    scan_id: UUID
    consumer: Symbol
    recipe_version: Symbol
    event_key: Symbol
    request_sha256: SHA256
    request: ScanRequest
    owner_id: UUID
    operation_id: UUID
    trace_id: UUID
    recorded_at: AwareDatetime
    start_brain_sequence: Sequence
    end_brain_sequence: Sequence
    start_control_sequence: Sequence
    end_control_sequence: Sequence
    due_bucket: AwareDatetime | None = None
    work: tuple[ScheduledWork, ...] = Field(default=(), max_length=100)
    next_page: ScanPage | None = None
    model_requests: Literal[0] = 0

    @model_validator(mode="after")
    def exact_receipt(self) -> Self:
        if self.request.company_id != self.company_id or any(
            row.company_id != self.company_id for row in self.work
        ):
            raise ValueError("Scheduler receipt crosses its company")
        if self.request_sha256 != request_sha256(self.request):
            raise ValueError("Scheduler receipt differs from its exact request")
        if self.end_brain_sequence < self.start_brain_sequence or (
            self.end_control_sequence < self.start_control_sequence
        ):
            raise ValueError("Scheduler cursors cannot roll back")
        if len({row.eligibility.work.task_id for row in self.work}) != len(self.work):
            raise ValueError("Scheduler receipt duplicates work identities")
        return self


class ScanResult(ValueContract):
    """A replay returns an immutable prior observation and creates no new dispatch."""

    receipt: ScanReceipt
    replayed: Flag
