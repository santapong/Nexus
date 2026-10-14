"""Exact stop declarations cannot turn strings/extra flags into cancellation authority."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexus.company.management.cancellation_contracts import (
    CancellationCommand,
    InheritedCancellation,
    OwnerCancellation,
)
from nexus.company.management.plans import RunBinding


def target() -> RunBinding:
    return RunBinding(
        company_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        run_id=uuid4(),
        workflow_name="bounded.report",
        workflow_version="v1",
        model_profile="routine",
        model_registry_version="native-v1",
    )


@pytest.mark.parametrize("reason", ["", "   ", True, 42, "x" * 501])
def test_cancellation_reason_requires_bounded_exact_meaningful_text(reason: object) -> None:
    bound = target()
    with pytest.raises(ValueError):
        CancellationCommand.model_validate(
            {"company_id": bound.company_id, "target": bound, "reason": reason}
        )


def test_foreign_company_and_unknown_authority_flag_are_rejected() -> None:
    bound = target()
    for declaration in (
        {"company_id": uuid4(), "target": bound, "reason": "Stop"},
        {"company_id": bound.company_id, "target": bound, "reason": "Stop", "owner_approved": True},
    ):
        with pytest.raises(ValueError):
            CancellationCommand.model_validate(declaration)


@pytest.mark.parametrize("inherited", [True, "false", 0, 1])
def test_direct_cancellation_cannot_claim_inherited_or_coerce_a_flag(inherited: object) -> None:
    bound = target()
    record = OwnerCancellation(
        company_id=bound.company_id,
        cancellation_id=uuid4(),
        target=bound,
        registration_sha256="a" * 64,
        reason="Owner stop",
        owner_id=uuid4(),
        operation_id=uuid4(),
        audit_trace_id=uuid4(),
        recorded_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError):
        InheritedCancellation.model_validate(
            {
                "company_id": bound.company_id,
                "requested_task_id": bound.task_id,
                "ancestor_task_id": bound.task_id,
                "inherited": inherited,
                "cancellation": record,
            }
        )


def test_exact_command_roundtrip_retains_native_ids_and_reason() -> None:
    bound = target()
    declared = CancellationCommand(
        company_id=bound.company_id, target=bound, reason="Retain unknown billing, stop new work"
    )
    assert CancellationCommand.model_validate_json(declared.model_dump_json()) == declared
