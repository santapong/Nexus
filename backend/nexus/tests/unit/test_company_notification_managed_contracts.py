"""Managed notification selectors/declarations never carry caller effect authority."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
)


def selection() -> NativeNotificationSelection:
    return NativeNotificationSelection(
        company_id=UUID(int=1),
        draft_id=UUID(int=2),
        sender_task_id=UUID(int=3),
        plan=PlanRevisionRef(
            company_id=UUID(int=1),
            plan_id=UUID(int=4),
            plan_revision_id=UUID(int=5),
            revision=1,
            sha256="a" * 64,
        ),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", str(UUID(int=6))),
        ("run_id", str(UUID(int=7))),
        ("recipient", "attacker@example.invalid"),
        ("body", "caller-supplied private body"),
        ("approved", True),
        ("estimated_cost_usd", "0"),
    ],
)
def test_selector_rejects_actor_body_cost_or_approval_override(field: str, value: object) -> None:
    data = selection().model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        NativeNotificationSelection.model_validate(data)


def test_cross_company_plan_cannot_select_sender() -> None:
    data = selection().model_dump(mode="json")
    plan = selection().plan.model_copy(update={"company_id": UUID(int=99)})
    data["plan"] = plan.model_dump(mode="json")
    with pytest.raises(ValidationError):
        NativeNotificationSelection.model_validate(data)


def test_server_policy_defaults_disabled_with_positive_estimate_not_actual_bill() -> None:
    policy = NotificationPreparationPolicy(
        target=ResourceRef(company_id=UUID(int=1), resource_id=UUID(int=8)),
        resource_symbol="owner.notifications",
    )
    assert policy.enabled is False and policy.estimated_cost_usd == Decimal(".01")
    assert policy.workflow_name == "internal.owner-notification" and policy.workflow_version == "v1"


@pytest.mark.parametrize("amount", ["0", "-0.01", "6"])
def test_unqualified_zero_or_out_of_bound_estimate_is_rejected(amount: str) -> None:
    with pytest.raises(ValidationError):
        NotificationPreparationPolicy(
            target=ResourceRef(company_id=UUID(int=1), resource_id=UUID(int=8)),
            resource_symbol="owner.notifications",
            estimated_cost_usd=Decimal(amount),
        )
