"""Current owner-managed access DTOs; caller snapshots cannot authorize materialization."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.brain.base import BrainContract, Count, Flag, require_company

ResourceKind = Literal["source", "artifact", "entity", "claim", "context"]


class ResourceRef(BrainContract):
    resource_id: UUID


class ResourceGeneration(ResourceRef):
    """Resource-wide ACL generation plus effective current principal grant expiry."""

    generation: Count
    expires_at: AwareDatetime | None = None


class ResourceRecord(ResourceRef):
    """Immutable kind/identity and separate current availability/access generation."""

    kind: ResourceKind
    active: Flag
    acl_generation: Count
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ResourceAccessChange(BrainContract):
    """Owner service command; principal and resource membership need fresh DB checks."""

    resource: ResourceRef
    principal_id: UUID
    active: Flag
    expected_generation: Count
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def same_resource(self) -> Self:
        require_company(self.company_id, self.resource)
        return self


class ResourceAccessSnapshot(BrainContract):
    """Current grant observation, never a client permit or persistent access guarantee."""

    resource: ResourceRef
    principal_id: UUID
    active: Flag
    generation: Count
    resource_generation: Count
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def same_resource(self) -> Self:
        require_company(self.company_id, self.resource)
        return self


class AccessEvent(BrainContract):
    event_id: UUID
    resource: ResourceRef
    principal_id: UUID
    generation: Count
    active: Flag
    expires_at: AwareDatetime | None
    owner_id: UUID
    operation_id: UUID
    trace_id: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def same_resource(self) -> Self:
        require_company(self.company_id, self.resource)
        return self
