"""Literal permanent intent and complete exact target cannot be confused with company resume."""

from uuid import uuid4

import pytest

from nexus.api.company_management_control_routes import WorkCancellationIntent
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.tests.unit.test_company_cancellation_contracts import target


def declaration() -> WorkCancellationIntent:
    bound = target()
    return WorkCancellationIntent(
        intent="cancel_work_permanently",
        command=CancellationCommand(company_id=bound.company_id, target=bound, reason="Owner stop"),
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
    )


@pytest.mark.parametrize("intent", [None, True, False, 1, "cancel", "pause", "resume", "uncancel"])
def test_only_explicit_permanent_literal_is_a_cancellation_intent(intent: object) -> None:
    data = declaration().model_dump()
    data["intent"] = intent
    with pytest.raises(ValueError):
        WorkCancellationIntent.model_validate(data)


@pytest.mark.parametrize(
    "extra", ["owner_id", "actor_id", "active", "paused", "budget_usd", "verified"]
)
def test_cancellation_body_accepts_no_authority_activity_or_allowance_override(extra: str) -> None:
    data = declaration().model_dump()
    data[extra] = True
    with pytest.raises(ValueError):
        WorkCancellationIntent.model_validate(data)


def test_complete_exact_intent_roundtrip_retains_operation_and_target() -> None:
    data = declaration()
    assert WorkCancellationIntent.model_validate_json(data.model_dump_json()) == data


def test_incomplete_or_foreign_target_is_rejected_before_native_store() -> None:
    data = declaration().model_dump()
    foreign = {**data, "command": {**data["command"], "company_id": uuid4()}}
    with pytest.raises(ValueError):
        WorkCancellationIntent.model_validate(foreign)
    missing = {**data, "command": {**data["command"], "target": {}}}
    with pytest.raises(ValueError):
        WorkCancellationIntent.model_validate(missing)
