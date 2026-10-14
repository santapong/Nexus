"""Finite worker declarations are configuration only, never owner or work allowance."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import Flag
from nexus.company.brain.native_fact_contracts import NativeEventSelector
from nexus.company.management.base import SHA256, ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding


class WorkerSubject(ValueContract):
    """A server-selected native subject and exact expected resource; no current-state claim."""

    selector: NativeEventSelector
    resource: ResourceRef

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.selector.company_id, self.resource)
        return self


class NotificationWorkerRegistration(ValueContract):
    """Exact existing finite sender/plan/policy pins; decoding registers no work or credential."""

    schema_version: Literal["nexus.company.notification.worker.v1"] = (
        "nexus.company.notification.worker.v1"
    )
    company_id: UUID
    workspace_id: UUID
    registration_id: UUID
    consumer: Literal["nexus.notifications.worker"] = "nexus.notifications.worker"
    recipe_version: Literal["native-notification-read-v1"] = "native-notification-read-v1"
    sender: RunBinding
    plan: PlanRevisionRef
    catalog_sha256: SHA256
    notification_policy_sha256: SHA256
    preparation_policy_sha256: SHA256
    registered_at: AwareDatetime
    expires_at: AwareDatetime
    subjects: tuple[WorkerSubject, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def exact_registration(self) -> Self:
        require_company(
            self.company_id,
            self.sender,
            self.plan,
            *(row.resource for row in self.subjects),
            *(row.selector for row in self.subjects),
        )
        if (
            self.sender.workspace_id != self.workspace_id
            or (self.sender.workflow_name, self.sender.workflow_version, self.sender.model_profile)
            != ("internal.owner-notification", "v1", "notification.native.v1")
            or self.expires_at <= self.registered_at
            or len({canonical_sha256(row.selector) for row in self.subjects}) != len(self.subjects)
        ):
            raise ValueError("Notification worker declaration is unsupported or ambiguous")
        return self


class NotificationWorkerConfiguration(ValueContract):
    """Server controls default false; they cannot approve actions or bypass native permission."""

    enabled: Flag = False
    emit_fallback: Flag = False
    consume_events: Flag = False
    prepare_pending: Flag = False
    max_events: int = Field(default=32, ge=1, le=32)
    max_candidates: int = Field(default=8, ge=1, le=8)
    timeout_seconds: int = Field(default=30, ge=1, le=30)


class NotificationWorkerRegistrationFile(ValueContract):
    """Bounded immutable operator configuration has no token, body, endpoint or grant."""

    registration: NotificationWorkerRegistration
    configuration: NotificationWorkerConfiguration = Field(
        default_factory=NotificationWorkerConfiguration
    )


class WorkerTickResult(ValueContract):
    """Committed bounded metadata only; no message body, portable cursor or effect authority."""

    disposition: Literal["disabled", "quiet", "staged"]
    new_wakes: int = Field(default=0, ge=0, le=32)
    replayed_wakes: int = Field(default=0, ge=0, le=32)
    events_acknowledged: int = Field(default=0, ge=0, le=32)
    draft_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    action_ids: tuple[UUID, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def exact_disposition(self) -> Self:
        staged = bool(self.new_wakes or self.draft_ids or self.action_ids)
        if (
            len(set(self.draft_ids)) != len(self.draft_ids)
            or (self.disposition == "staged") != staged
            or (
                self.disposition == "disabled" and (self.replayed_wakes or self.events_acknowledged)
            )
        ):
            raise ValueError("Notification worker result differs from committed metadata")
        return self
