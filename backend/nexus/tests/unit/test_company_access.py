"""Live directory policy prevents token and payload scope from becoming authority."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.access import (
    AccessDeniedError,
    Capability,
    CompanyDirectory,
    PrincipalAccess,
    VerifiedIdentity,
    WorkAccess,
    require_proposal_scope,
    resolve_principal_access,
    resolve_work_scope,
)
from nexus.company.contracts.actions import ActionProposal
from nexus.tests.unit.test_company_foundation import ACTOR, COMPANY, OWNER, TASK, TRACE, proposal

WORKSPACE = UUID(int=70)


def access(principal_id: UUID = ACTOR) -> PrincipalAccess:
    """Construct current directory state, independent of JWT role claims."""
    return PrincipalAccess(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        principal_id=principal_id,
        owner_id=OWNER,
        membership_role="owner" if principal_id == OWNER else "member",
        company_active=True,
        workspace_active=True,
        principal_active=True,
        membership_active=True,
    )


def directory(snapshot: PrincipalAccess | None = None) -> AsyncMock:
    """Fake only the independent directory boundary; exercise real permission policy."""
    result = AsyncMock(spec=CompanyDirectory)
    result.lookup_principal.return_value = snapshot or access()
    result.lookup_work.return_value = WorkAccess(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        active=True,
        allowed_principals=(ACTOR,),
    )
    return result


async def principal(
    source: AsyncMock, capability: Capability = Capability.INTERNAL_PROPOSAL
) -> PrincipalAccess:
    """Resolve a normal member through the real current-state resolver."""
    return await resolve_principal_access(
        VerifiedIdentity(principal_id=ACTOR, workspace_id=WORKSPACE),
        source,
        company_id=COMPANY,
        capability=capability,
        task_id=TASK,
        trace_id=TRACE,
    )


async def test_live_member_can_propose_only_its_registered_work() -> None:
    source = directory()
    current = await principal(source)
    scope = await resolve_work_scope(
        current, source, task_id=TASK, trace_id=TRACE, capability=Capability.INTERNAL_PROPOSAL
    )
    require_proposal_scope(proposal(), scope)
    assert scope.principal_id == ACTOR and scope.company_id == COMPANY


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": UUID(int=99)},
        {"workspace_id": UUID(int=99)},
        {"principal_id": OWNER},
        {"company_active": False},
        {"workspace_active": False},
        {"principal_active": False},
        {"membership_active": False},
        {"membership_role": "owner"},
    ],
)
async def test_foreign_inactive_revoked_or_false_owner_directory_state_denies(
    change: dict[str, object],
) -> None:
    source = directory(PrincipalAccess.model_validate(access().model_dump() | change))
    with pytest.raises(AccessDeniedError):
        await principal(source)


async def test_missing_membership_or_directory_failure_never_falls_back() -> None:
    source = directory()
    source.lookup_principal.return_value = None
    with pytest.raises(AccessDeniedError):
        await principal(source)
    source.lookup_principal.side_effect = RuntimeError("Directory unavailable")
    with pytest.raises(RuntimeError):
        await principal(source)


@pytest.mark.parametrize("capability", [Capability.APPROVE, Capability.PAUSE, Capability.GRANT])
async def test_members_and_admins_cannot_mint_owner_authority(capability: Capability) -> None:
    for role in ("member", "admin", "viewer"):
        source = directory(
            PrincipalAccess.model_validate(access().model_dump() | {"membership_role": role})
        )
        with pytest.raises(AccessDeniedError):
            await principal(source, capability)
    owner = access(OWNER)
    assert (
        await resolve_principal_access(
            VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE),
            directory(owner),
            company_id=COMPANY,
            capability=capability,
            task_id=TASK,
            trace_id=TRACE,
        )
        == owner
    )


async def test_viewer_can_read_but_cannot_propose_internal_work() -> None:
    source = directory(
        PrincipalAccess.model_validate(access().model_dump() | {"membership_role": "viewer"})
    )
    assert (await principal(source, Capability.READ)).membership_role == "viewer"
    with pytest.raises(AccessDeniedError):
        await principal(source)


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": UUID(int=99)},
        {"workspace_id": UUID(int=99)},
        {"task_id": UUID(int=99)},
        {"trace_id": UUID(int=99)},
        {"actor_id": OWNER},
        {"active": False},
        {"allowed_principals": ()},
    ],
)
async def test_foreign_spoofed_or_inaccessible_registered_work_denies(
    change: dict[str, object],
) -> None:
    source = directory()
    source.lookup_work.return_value = WorkAccess.model_validate(
        source.lookup_work.return_value.model_dump() | change
    )
    with pytest.raises(AccessDeniedError):
        await resolve_work_scope(
            access(),
            source,
            task_id=TASK,
            trace_id=TRACE,
            capability=Capability.INTERNAL_PROPOSAL,
        )


async def test_unknown_work_denies_and_owner_can_approve_another_actor_work() -> None:
    source = directory()
    owner_scope = await resolve_work_scope(
        access(OWNER), source, task_id=TASK, trace_id=TRACE, capability=Capability.APPROVE
    )
    assert owner_scope.principal_id == OWNER
    source.lookup_work.return_value = None
    with pytest.raises(AccessDeniedError):
        await resolve_work_scope(
            access(), source, task_id=TASK, trace_id=TRACE, capability=Capability.READ
        )


@pytest.mark.parametrize("field", ["company_id", "actor_id", "task_id", "trace_id"])
async def test_action_payload_cannot_spoof_server_derived_identity(field: str) -> None:
    scope = await resolve_work_scope(
        access(),
        directory(),
        task_id=TASK,
        trace_id=TRACE,
        capability=Capability.INTERNAL_PROPOSAL,
    )
    changed = ActionProposal.model_validate(proposal().model_dump() | {field: UUID(int=99)})
    with pytest.raises(AccessDeniedError):
        require_proposal_scope(changed, scope)


async def test_each_resolution_rechecks_current_membership_instead_of_caching() -> None:
    source = directory()
    await principal(source)
    source.lookup_principal.return_value = PrincipalAccess.model_validate(
        access().model_dump() | {"membership_active": False}
    )
    with pytest.raises(AccessDeniedError):
        await principal(source)
    assert source.lookup_principal.await_count == 2


async def test_explicit_viewer_list_does_not_bypass_journal_actor_or_owner_read_policy() -> None:
    source = directory()
    source.lookup_work.return_value = WorkAccess.model_validate(
        source.lookup_work.return_value.model_dump()
        | {"actor_id": OWNER, "allowed_principals": (ACTOR,)}
    )
    with pytest.raises(AccessDeniedError):
        await resolve_work_scope(
            access(), source, task_id=TASK, trace_id=TRACE, capability=Capability.READ
        )


async def test_current_owner_can_audit_existing_inactive_work_without_execution_authority() -> None:
    source = directory()
    source.lookup_work.return_value = WorkAccess.model_validate(
        source.lookup_work.return_value.model_dump() | {"active": False, "allowed_principals": ()}
    )
    result = await resolve_work_scope(
        access(OWNER), source, task_id=TASK, trace_id=TRACE, capability=Capability.READ
    )
    assert result.principal_id == OWNER
    for capability in (Capability.APPROVE, Capability.INTERNAL_PROPOSAL):
        with pytest.raises(AccessDeniedError):
            await resolve_work_scope(
                access(OWNER), source, task_id=TASK, trace_id=TRACE, capability=capability
            )
    with pytest.raises(AccessDeniedError):
        await resolve_work_scope(
            access(), source, task_id=TASK, trace_id=TRACE, capability=Capability.READ
        )


async def test_work_lookup_cannot_be_used_for_owner_control_audit_identity() -> None:
    with pytest.raises(AccessDeniedError):
        await resolve_work_scope(
            access(OWNER), directory(), task_id=TASK, trace_id=TRACE, capability=Capability.PAUSE
        )


async def test_real_owner_without_current_owner_membership_cannot_approve() -> None:
    downgraded = PrincipalAccess.model_validate(
        access(OWNER).model_dump() | {"membership_role": "member"}
    )
    with pytest.raises(AccessDeniedError):
        await resolve_principal_access(
            VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE),
            directory(downgraded),
            company_id=COMPANY,
            capability=Capability.APPROVE,
            task_id=TASK,
            trace_id=TRACE,
        )
