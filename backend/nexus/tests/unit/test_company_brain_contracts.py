"""Brain schema guards precede retrieval; a decoded DTO is never an authority grant."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import BrainReadScope, SourceTime, ValidityInterval

COMPANY, WORKSPACE, PRINCIPAL, OPERATION, TRACE, TASK = (UUID(int=i) for i in range(1, 7))


def read_scope(**updates: object) -> BrainReadScope:
    return BrainReadScope.model_validate(
        {
            "company_id": COMPANY,
            "workspace_id": WORKSPACE,
            "principal_id": PRINCIPAL,
            "operation_id": OPERATION,
            "trace_id": TRACE,
        }
        | updates
    )


def test_company_read_scope_has_no_work_allowance_or_implicit_actor() -> None:
    scope = read_scope()
    assert scope.task_id is None and scope.actor_id is None
    with pytest.raises(ValidationError):
        read_scope(budget_usd="100", role="owner")


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": TASK},
        {"task_id": TASK, "actor_id": PRINCIPAL},
        {"task_id": OPERATION, "actor_id": PRINCIPAL, "task_trace_id": TRACE},
    ],
)
def test_work_binding_is_complete_and_control_identity_cannot_mint_work(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        read_scope(**changes)


def test_owner_read_can_name_registered_actor_without_impersonating_it() -> None:
    scope = read_scope(task_id=TASK, actor_id=UUID(int=99), task_trace_id=UUID(int=100))
    assert scope.principal_id != scope.actor_id and scope.trace_id != scope.task_trace_id


@pytest.mark.parametrize(
    "precision,value",
    [
        ("unknown", None),
        ("month", "2026-09"),
        ("day", "2026-10-01"),
        ("instant", "2026-10-13T12:00:00+07:00"),
    ],
)
def test_source_time_retains_exact_precision_without_imputing_ingestion(
    precision: str,
    value: str | None,
) -> None:
    result = SourceTime.model_validate(
        {"precision": precision, "value": value, "basis": "synthetic"}
    )
    assert result.value == value and result.precision == precision


@pytest.mark.parametrize(
    "precision,value",
    [
        ("unknown", "2026-10-13"),
        ("day", None),
        ("day", "2026-02-30"),
        ("month", "2026-09-01"),
        ("day", "2026-10-01T12:00:00Z"),
        ("instant", "2026-10-13T12:00:00"),
    ],
)
def test_fabricated_invalid_or_ambiguous_source_instants_fail(
    precision: str,
    value: str | None,
) -> None:
    with pytest.raises(ValidationError):
        SourceTime.model_validate({"precision": precision, "value": value, "basis": "source"})


def test_valid_interval_rejects_reversed_or_naive_instants() -> None:
    with pytest.raises(ValidationError):
        ValidityInterval(
            start=datetime(2026, 10, 14, tzinfo=UTC), end=datetime(2026, 10, 13, tzinfo=UTC)
        )
    with pytest.raises(ValidationError):
        ValidityInterval(start=datetime(2026, 10, 13))


@pytest.mark.parametrize("value", [True, 1.0, "1", -1, 0])
def test_acl_generation_requires_an_exact_positive_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        ResourceAccessChange.model_validate(
            {
                "company_id": COMPANY,
                "resource": ResourceRef(company_id=COMPANY, resource_id=UUID(int=20)),
                "principal_id": PRINCIPAL,
                "active": True,
                "expected_generation": value,
            },
            strict=False,
        )


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
def test_acl_flags_stay_literal_even_under_a_non_strict_http_decoder(value: object) -> None:
    with pytest.raises(ValidationError):
        ResourceAccessChange.model_validate(
            {
                "company_id": COMPANY,
                "resource": ResourceRef(company_id=COMPANY, resource_id=UUID(int=20)),
                "principal_id": PRINCIPAL,
                "active": value,
                "expected_generation": 1,
            },
            strict=False,
        )


def test_acl_resource_cannot_cross_the_parent_company() -> None:
    with pytest.raises(ValidationError):
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=UUID(int=99), resource_id=UUID(int=20)),
            principal_id=PRINCIPAL,
            active=True,
            expected_generation=1,
        )
