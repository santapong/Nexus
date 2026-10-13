"""Explicit internal standing grants bind owner-declared plan and charter revisions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.harness.approvals import ApprovalContext
from nexus.harness.standing_contracts import (
    StandingDeniedError,
    StandingGrant,
    ToolPermission,
    WorkAuthority,
    canonical_grant,
    grant_hash,
    require_binding_update,
    require_standing_policy,
)
from nexus.tests.unit.test_company_foundation import ACTOR, COMPANY, NOW, OWNER, TASK, proposal

PLAN, CHARTER, GRANT = (UUID(int=i) for i in (701, 702, 703))


def binding() -> WorkAuthority:
    return WorkAuthority(
        company_id=COMPANY,
        task_id=TASK,
        plan_id=PLAN,
        plan_revision=1,
        charter_id=CHARTER,
        charter_revision=1,
    )


def grant() -> StandingGrant:
    return StandingGrant(
        **binding().model_dump(),
        grant_id=GRANT,
        actor_id=ACTOR,
        owner_id=OWNER,
        policy_version="policy-1",
        price_version="prices-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=8),
        max_action_cost_usd=Decimal("0.50"),
        permissions=(
            ToolPermission(
                tool="fake.internal.draft.v1", tool_version="v1", resource="fixture:report"
            ),
        ),
    )


def action() -> ActionProposal:
    return ActionProposal.model_validate(
        proposal().model_dump()
        | {
            "tool": "fake.internal.draft.v1",
            "tool_version": "v1",
            "resource": "fixture:report",
        }
    )


def context() -> ApprovalContext:
    return ApprovalContext(
        company_id=COMPANY,
        owner_id=OWNER,
        actor_id=ACTOR,
        now=NOW,
        policy_version="policy-1",
        price_version="prices-1",
        paused=False,
        resources=action().preconditions,
    )


def test_owner_grant_allows_exact_internal_action_without_per_action_approval() -> None:
    require_standing_policy(grant(), action(), context(), binding())
    read_grant = StandingGrant.model_validate(
        grant().model_dump()
        | {
            "permissions": [
                {
                    "tool": "fake.internal.read.v1",
                    "tool_version": "v1",
                    "resource": "fixture:report",
                }
            ]
        }
    )
    read = ActionProposal.model_validate(action().model_dump() | {"tool": "fake.internal.read.v1"})
    require_standing_policy(read_grant, read, context(), binding())


@pytest.mark.parametrize("field", ["tool", "tool_version", "resource"])
@pytest.mark.parametrize("value", ["*", "fake.*", "resource?", "resource[1]"])
def test_tool_permissions_cannot_express_wildcards(field: str, value: str) -> None:
    data = grant().model_dump()
    data["permissions"][0][field] = value
    with pytest.raises(ValidationError):
        StandingGrant.model_validate(data)


@pytest.mark.parametrize("cost", [True, False, 0.1, float("inf"), Decimal("-0.01")])
def test_grant_cost_rejects_ambiguous_or_invalid_input(cost: object) -> None:
    with pytest.raises(ValidationError):
        StandingGrant.model_validate(grant().model_dump() | {"max_action_cost_usd": cost})


@pytest.mark.parametrize("permissions", [(), (grant().permissions[0], grant().permissions[0])])
def test_empty_or_duplicate_permissions_cannot_grant_authority(
    permissions: tuple[ToolPermission, ...],
) -> None:
    with pytest.raises(ValidationError):
        StandingGrant.model_validate(grant().model_dump() | {"permissions": permissions})


@pytest.mark.parametrize(
    "expires",
    [NOW, NOW - timedelta(seconds=1), NOW + timedelta(hours=25), NOW.replace(tzinfo=None)],
)
def test_grants_have_finite_aware_positive_lifetime(expires: object) -> None:
    with pytest.raises(ValidationError):
        StandingGrant.model_validate(grant().model_dump() | {"expires_at": expires})


@pytest.mark.parametrize(
    "change",
    [
        {"tool": "send_email"},
        {"tool": "fake.internal.other.v1"},
        {"tool_version": "v2"},
        {"resource": "fixture:other"},
        {"actor_id": OWNER},
        {"company_id": UUID(int=999)},
        {"task_id": UUID(int=999)},
        {"policy_version": "policy-2"},
        {"price_version": "prices-2"},
        {"estimated_cost_usd": "0.500001"},
    ],
)
def test_changed_scope_external_or_unregistered_tools_and_cost_are_denied(
    change: dict[str, object],
) -> None:
    changed = ActionProposal.model_validate(action().model_dump() | change)
    with pytest.raises(StandingDeniedError):
        require_standing_policy(grant(), changed, context(), binding())


@pytest.mark.parametrize(
    "change",
    [
        {"paused": True},
        {"now": NOW + timedelta(hours=8)},
        {"now": NOW - timedelta(seconds=1)},
        {"owner_id": ACTOR},
        {"actor_id": OWNER},
        {"company_id": UUID(int=999)},
        {"policy_version": "policy-2"},
        {"price_version": "prices-2"},
        {"resources": ()},
    ],
)
def test_current_pause_expiry_revisions_and_missing_resources_deny(
    change: dict[str, object],
) -> None:
    changed = ApprovalContext.model_validate(context().model_dump() | change)
    with pytest.raises(StandingDeniedError):
        require_standing_policy(grant(), action(), changed, binding())


@pytest.mark.parametrize(
    "change",
    [
        {"plan_id": UUID(int=999)},
        {"plan_revision": 2},
        {"charter_id": UUID(int=999)},
        {"charter_revision": 2},
    ],
)
def test_owner_binding_changes_invalidate_existing_grant(change: dict[str, object]) -> None:
    current = WorkAuthority.model_validate(binding().model_dump() | change)
    with pytest.raises(StandingDeniedError):
        require_standing_policy(grant(), action(), context(), current)


def test_current_resource_revisions_cannot_be_missing_changed_or_ambiguous() -> None:
    for resources in (
        (ResourceRevision(resource=action().preconditions[0].resource, revision="changed"),),
        action().preconditions + action().preconditions,
    ):
        changed = ApprovalContext.model_validate(context().model_dump() | {"resources": resources})
        with pytest.raises(StandingDeniedError):
            require_standing_policy(grant(), action(), changed, binding())


def test_client_cannot_add_self_issued_risk_class_to_the_grant() -> None:
    with pytest.raises(ValidationError):
        StandingGrant.model_validate(grant().model_dump() | {"risk_class": "internal"})


@pytest.mark.parametrize(
    "tool", ["send_email", "grant.issue", "policy.write", "fake.internal.other.v1"]
)
def test_owner_snapshot_cannot_grant_external_delegation_or_policy_tools(tool: str) -> None:
    unsupported = StandingGrant.model_validate(
        grant().model_dump()
        | {"permissions": [{"tool": tool, "tool_version": "v1", "resource": "fixture:report"}]}
    )
    changed = ActionProposal.model_validate(action().model_dump() | {"tool": tool})
    with pytest.raises(StandingDeniedError):
        require_standing_policy(unsupported, changed, context(), binding())


def test_grant_hash_is_deterministic_and_binds_every_permission_and_revision() -> None:
    assert canonical_grant(grant()) == canonical_grant(
        StandingGrant.model_validate_json(grant().model_dump_json())
    )
    changed = StandingGrant.model_validate(grant().model_dump() | {"plan_revision": 2})
    assert grant_hash(grant()) != grant_hash(changed)


def test_binding_edits_are_monotone_and_exact_duplicates_are_idempotent() -> None:
    require_binding_update(binding(), binding())
    newer = WorkAuthority.model_validate(binding().model_dump() | {"plan_revision": 2})
    require_binding_update(binding(), newer)
    for change in ({"plan_revision": 1}, {"plan_id": UUID(int=999)}, {"charter_revision": 0}):
        with pytest.raises((StandingDeniedError, ValidationError)):
            require_binding_update(newer, WorkAuthority.model_validate(newer.model_dump() | change))
