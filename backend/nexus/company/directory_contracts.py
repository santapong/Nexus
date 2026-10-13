"""Owner-controlled directory commands and non-minting lifetime allocation rules."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, field_validator, model_validator

from nexus.company.access import CompanyControlScope
from nexus.company.contracts.base import USD, Contract

MembershipRole = Literal["owner", "admin", "member", "viewer"]


class DirectoryDeniedError(ValueError):
    """Persisted identity, ownership, registration or allocation is unavailable."""


class CompanyRegistration(Contract):
    """Trusted operator bootstrap after initial CompanyControl is persisted."""

    workspace_id: UUID
    owner_id: UUID


class MembershipChange(Contract):
    """Actual owner-controlled current role/activity; never a JWT role claim."""

    principal_id: UUID
    role: MembershipRole
    principal_active: StrictBool = True
    membership_active: StrictBool = True


class WorkRegistration(Contract):
    """A server-authored immutable logical task; callers cannot choose its root.

    Future HTTP adapters generate task and trace IDs server-side. This internal
    command is accepted only under the actual current owner's audit identity.
    """

    workspace_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    parent_task_id: UUID | None = None
    allocation_usd: USD
    allowed_principals: tuple[UUID, ...] = Field(min_length=1, max_length=100)

    @field_validator("allocation_usd", mode="before")
    @classmethod
    def require_exact_allocation(cls, value: object) -> object:
        """Prevent float or boolean input from altering an exact budget slice."""
        if isinstance(value, (float, bool)):
            raise ValueError("allocation must use exact decimals")
        return value

    @model_validator(mode="after")
    def require_distinct_identity_and_grants(self) -> Self:
        """Bound the actor to unique explicitly listed principals and no self-parent."""
        if self.parent_task_id == self.task_id:
            raise ValueError("work cannot be its own parent")
        if len(self.allowed_principals) != len(set(self.allowed_principals)):
            raise ValueError("allowed principals must be unique")
        if self.actor_id not in self.allowed_principals:
            raise ValueError("registered actor must be an allowed principal")
        return self


class WorkAllocation(Contract):
    """Partitioned lifetime allocation and direct task ledger amounts."""

    workspace_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    parent_task_id: UUID | None
    root_task_id: UUID
    allocation_usd: USD
    delegated_usd: USD
    spent_usd: USD
    held_usd: USD
    active: StrictBool

    @property
    def available_usd(self) -> Decimal:
        """Return the unused own slice; overbilling blocks rather than mints money."""
        return max(
            Decimal(0), self.allocation_usd - self.delegated_usd - self.spent_usd - self.held_usd
        )

    @model_validator(mode="after")
    def require_valid_partition(self) -> Self:
        """Every root is itself; each child keeps an existing separate root."""
        if self.delegated_usd > self.allocation_usd:
            raise ValueError("delegation exceeds the allocated lifetime slice")
        if self.parent_task_id is None and self.root_task_id != self.task_id:
            raise ValueError("root work identity must equal its task identity")
        if self.parent_task_id == self.task_id or (
            self.parent_task_id is not None and self.root_task_id == self.task_id
        ):
            raise ValueError("child work cannot become its own root or parent")
        return self


def validate_registration(
    registration: WorkRegistration,
    scope: CompanyControlScope,
    *,
    owner_id: UUID,
    work_cap_usd: Decimal,
    parent: WorkAllocation | None,
) -> UUID:
    """Validate immutable identity/partition and derive its existing root task ID.

    Persisted owner/membership and lock ownership remain store responsibilities.
    This pure check never consumes a budget or confers external authority.
    """
    registration = WorkRegistration.model_validate(registration.model_dump())
    if scope.company_id != registration.company_id or scope.principal_id != owner_id:
        raise DirectoryDeniedError("registration requires the actual company owner")
    if scope.operation_id == registration.task_id:
        raise DirectoryDeniedError("control audit identity cannot become work")
    if registration.parent_task_id is None:
        if parent is not None or registration.allocation_usd > work_cap_usd:
            raise DirectoryDeniedError("root allocation exceeds its lifetime work cap")
        return registration.task_id
    if parent is None:
        raise DirectoryDeniedError("registered parent is unavailable")
    parent = WorkAllocation.model_validate(parent.model_dump())
    if not parent.active or (parent.company_id, parent.workspace_id, parent.task_id) != (
        registration.company_id,
        registration.workspace_id,
        registration.parent_task_id,
    ):
        raise DirectoryDeniedError("parent belongs to another scope or is inactive")
    if registration.allocation_usd > parent.available_usd:
        raise DirectoryDeniedError("parent has insufficient undelegated lifetime allowance")
    return parent.root_task_id
