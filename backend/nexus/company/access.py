"""Server-derived company access policy, independent of HTTP and database adapters."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import Contract
from nexus.harness.journal_contracts import LedgerScope


class AccessDeniedError(ValueError):
    """Current identity, directory state or permission does not authorize access."""


class Capability(StrEnum):
    """Separate proposed internal work from consequential owner controls."""

    READ = "read"
    INTERNAL_PROPOSAL = "internal_proposal"
    APPROVE = "approve"
    PAUSE = "pause"
    GRANT = "grant"
    INITIALIZE = "initialize"


class VerifiedIdentity(BaseModel):
    """Verified JWT subject/workspace only; token role claims grant no authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    principal_id: UUID
    workspace_id: UUID


class PrincipalAccess(Contract):
    """Live trusted directory snapshot, not an externally accepted grant."""

    workspace_id: UUID
    principal_id: UUID
    owner_id: UUID
    membership_role: Literal["owner", "admin", "member", "viewer"]
    company_active: StrictBool
    workspace_active: StrictBool
    principal_active: StrictBool
    membership_active: StrictBool


class WorkAccess(Contract):
    """Server-registered work identity and current access; no client task creation."""

    workspace_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    active: StrictBool
    allowed_principals: tuple[UUID, ...]


class CompanyControlScope(Contract):
    """Owner control audit identity; cannot be supplied as a work cost allowance."""

    principal_id: UUID
    operation_id: UUID
    trace_id: UUID


class CompanyDirectory(Protocol):
    """Implement with fresh DB reads using explicit workspace/company RLS contexts."""

    async def lookup_principal(
        self, identity: VerifiedIdentity, *, task_id: UUID, trace_id: UUID
    ) -> PrincipalAccess | None:
        """Read active mapping, real owner and current membership for verified identity."""
        ...

    async def lookup_work(
        self, company_id: UUID, task_id: UUID, *, trace_id: UUID
    ) -> WorkAccess | None:
        """Read registered work and its actor/trace; absence must never create work."""
        ...


def require_capability(access: PrincipalAccess, capability: Capability) -> None:
    """Fail closed on inactive state, false owner roles and unsupported capabilities."""
    if not all(
        (
            access.company_active,
            access.workspace_active,
            access.principal_active,
            access.membership_active,
        )
    ):
        raise AccessDeniedError("Company identity or membership is inactive")
    owner = access.principal_id == access.owner_id and access.membership_role == "owner"
    if access.membership_role == "owner" and not owner:
        raise AccessDeniedError("Membership role disagrees with the actual owner")
    if capability == Capability.READ:
        return
    if capability == Capability.INTERNAL_PROPOSAL and access.membership_role != "viewer":
        return
    if (
        capability
        in {Capability.APPROVE, Capability.PAUSE, Capability.GRANT, Capability.INITIALIZE}
        and owner
    ):
        return
    raise AccessDeniedError("Current membership lacks this capability")


async def resolve_principal_access(
    identity: VerifiedIdentity,
    directory: CompanyDirectory,
    *,
    company_id: UUID,
    capability: Capability,
    task_id: UUID,
    trace_id: UUID,
) -> PrincipalAccess:
    """Recheck live mapping and membership; JWT and request company IDs are hints only."""
    access = await directory.lookup_principal(identity, task_id=task_id, trace_id=trace_id)
    if access is None or (access.company_id, access.workspace_id, access.principal_id) != (
        company_id,
        identity.workspace_id,
        identity.principal_id,
    ):
        raise AccessDeniedError("No current company membership for this identity")
    require_capability(access, capability)
    return access


async def resolve_work_scope(
    access: PrincipalAccess,
    directory: CompanyDirectory,
    *,
    task_id: UUID,
    trace_id: UUID,
    capability: Capability,
) -> LedgerScope:
    """Bind a registered task/trace to its current actor or owner, never impersonating."""
    require_capability(access, capability)
    work = await directory.lookup_work(access.company_id, task_id, trace_id=trace_id)
    return bind_work_scope(access, work, task_id=task_id, trace_id=trace_id, capability=capability)


def bind_work_scope(
    access: PrincipalAccess,
    work: WorkAccess | None,
    *,
    task_id: UUID,
    trace_id: UUID,
    capability: Capability,
) -> LedgerScope:
    """Apply one actor/owner policy to fresh work at lookup and materialization boundaries."""
    require_capability(access, capability)
    owner = access.principal_id == access.owner_id and access.membership_role == "owner"
    if (
        work is None
        or (not work.active and not (owner and capability == Capability.READ))
        or (work.company_id, work.workspace_id, work.task_id, work.trace_id)
        != (access.company_id, access.workspace_id, task_id, trace_id)
    ):
        raise AccessDeniedError("Registered work is absent, inactive or belongs to another scope")
    actor = access.principal_id == work.actor_id and access.principal_id in work.allowed_principals
    if capability == Capability.INTERNAL_PROPOSAL and not actor:
        raise AccessDeniedError("Only the registered actor may propose this work's actions")
    if capability == Capability.READ and not (actor or owner):
        raise AccessDeniedError("Journal work reads require its actor or current owner")
    if capability not in {Capability.READ, Capability.INTERNAL_PROPOSAL, Capability.APPROVE}:
        raise AccessDeniedError("Company controls require a separate operation audit identity")
    return LedgerScope(
        company_id=work.company_id,
        principal_id=access.principal_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
    )


def require_proposal_scope(action: ActionProposal, scope: LedgerScope) -> None:
    """Reject payload company/actor/task/trace spoofing against server-derived work scope."""
    if (action.company_id, action.actor_id, action.task_id, action.trace_id) != (
        scope.company_id,
        scope.principal_id,
        scope.task_id,
        scope.trace_id,
    ):
        raise AccessDeniedError("Proposal does not match its authenticated registered work scope")
