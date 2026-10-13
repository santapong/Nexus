"""Frozen scope and lifetime quota-partition acceptance, without DB authority claims."""

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.access import CompanyControlScope
from nexus.company.directory_contracts import (
    DirectoryDeniedError,
    WorkAllocation,
    WorkRegistration,
    validate_registration,
)

COMPANY, WORKSPACE, OWNER, ACTOR, TASK, TRACE = (UUID(int=i) for i in range(1, 7))


def registration(**updates: object) -> WorkRegistration:
    data: dict[str, object] = {
        "company_id": COMPANY,
        "workspace_id": WORKSPACE,
        "task_id": TASK,
        "trace_id": TRACE,
        "actor_id": ACTOR,
        "allocation_usd": Decimal("0.50"),
        "allowed_principals": (ACTOR,),
    }
    return WorkRegistration.model_validate(data | updates)


def control(**updates: object) -> CompanyControlScope:
    return CompanyControlScope.model_validate(
        {
            "company_id": COMPANY,
            "principal_id": OWNER,
            "operation_id": UUID(int=9),
            "trace_id": UUID(int=10),
        }
        | updates
    )


def parent(**updates: object) -> WorkAllocation:
    data: dict[str, object] = {
        "company_id": COMPANY,
        "workspace_id": WORKSPACE,
        "task_id": UUID(int=11),
        "trace_id": UUID(int=12),
        "actor_id": ACTOR,
        "root_task_id": UUID(int=11),
        "parent_task_id": None,
        "allocation_usd": Decimal("1.00"),
        "delegated_usd": Decimal("0.20"),
        "spent_usd": Decimal("0.10"),
        "held_usd": Decimal("0.20"),
        "active": True,
    }
    return WorkAllocation.model_validate(data | updates)


def test_root_registration_is_owner_bound_and_derives_its_root_identity() -> None:
    assert (
        validate_registration(
            registration(), control(), owner_id=OWNER, work_cap_usd=Decimal("1.00"), parent=None
        )
        == TASK
    )


def test_child_partition_consumes_only_parent_undelegated_unspent_unheld_allowance() -> None:
    current = parent()
    child = registration(parent_task_id=current.task_id)
    assert current.available_usd == Decimal("0.50")
    assert (
        validate_registration(
            child, control(), owner_id=OWNER, work_cap_usd=Decimal("1.00"), parent=current
        )
        == current.root_task_id
    )
    with pytest.raises(DirectoryDeniedError):
        validate_registration(
            registration(parent_task_id=current.task_id, allocation_usd=Decimal("0.500001")),
            control(),
            owner_id=OWNER,
            work_cap_usd=Decimal("1.00"),
            parent=current,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"company_id": UUID(int=99)},
        {"principal_id": ACTOR},
        {"operation_id": TASK},
    ],
)
def test_control_identity_cannot_mint_or_impersonate_work(updates: dict[str, object]) -> None:
    with pytest.raises(DirectoryDeniedError):
        validate_registration(
            registration(),
            control(**updates),
            owner_id=OWNER,
            work_cap_usd=Decimal("1.00"),
            parent=None,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"allocation_usd": Decimal("-1")},
        {"allocation_usd": Decimal("Infinity")},
        {"allocation_usd": 0.5},
        {"allowed_principals": ()},
        {"allowed_principals": (ACTOR, ACTOR)},
        {"allowed_principals": (OWNER,)},
        {"parent_task_id": TASK},
        {"root_task_id": UUID(int=77)},
    ],
)
def test_registration_rejects_ambiguous_money_identity_or_grants(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        registration(**updates)


def test_parent_scope_activity_and_lineage_must_match() -> None:
    for updates in (
        {"company_id": UUID(int=99)},
        {"workspace_id": UUID(int=99)},
        {"active": False},
    ):
        current = parent(**updates)
        with pytest.raises(DirectoryDeniedError):
            validate_registration(
                registration(parent_task_id=current.task_id),
                control(),
                owner_id=OWNER,
                work_cap_usd=Decimal("1.00"),
                parent=current,
            )
    with pytest.raises(DirectoryDeniedError):
        validate_registration(
            registration(parent_task_id=UUID(int=11)),
            control(),
            owner_id=OWNER,
            work_cap_usd=Decimal("1.00"),
            parent=None,
        )


def test_overbilling_does_not_create_a_negative_or_resettable_allowance() -> None:
    assert parent(spent_usd=Decimal("2.00")).available_usd == Decimal(0)
    with pytest.raises(DirectoryDeniedError):
        validate_registration(
            registration(allocation_usd=Decimal("1.000001")),
            control(),
            owner_id=OWNER,
            work_cap_usd=Decimal("1.00"),
            parent=None,
        )


def test_directory_contract_roundtrip_retains_exact_work_and_money() -> None:
    value = registration()
    assert WorkRegistration.model_validate_json(value.model_dump_json()) == value
    assert WorkAllocation.model_validate_json(parent().model_dump_json()) == parent()
