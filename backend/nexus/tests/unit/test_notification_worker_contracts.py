"""Durable notification metadata cannot contain authority or declare unbound outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_worker_contracts import (
    NotificationEnqueueResult,
    NotificationSegmentResult,
)


def command() -> SegmentCommand:
    return SegmentCommand(
        company_id=UUID(int=1),
        task_id=UUID(int=2),
        trace_id=UUID(int=3),
        actor_id=UUID(int=4),
        workspace_id=UUID(int=5),
        run_id=UUID(int=6),
        action_id=UUID(int=7),
        segment_id=UUID(int=8),
    )


def test_exact_command_and_unconfirmed_billing_are_descriptive_only() -> None:
    queued = NotificationEnqueueResult(
        company_id=command().company_id,
        command=command(),
        disposition="enqueued",
        observed_at=datetime.now(UTC),
    )
    result = NotificationSegmentResult(
        company_id=queued.company_id,
        command=queued.command,
        status="outcome_unknown",
        observed_at=datetime.now(UTC),
    )
    assert result.billing == "unconfirmed"
    assert NotificationSegmentResult.model_validate_json(result.model_dump_json()) == result
    assert not hasattr(result, "call_permit") and not hasattr(queued, "approval")


@pytest.mark.parametrize("field", ["call_permit", "approval", "token", "body", "actual_usd"])
def test_worker_metadata_rejects_effect_authority_and_private_or_fabricated_cost_fields(
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        NotificationSegmentResult.model_validate(
            {
                "company_id": command().company_id,
                "command": command(),
                "status": "blocked",
                "observed_at": datetime.now(UTC),
                field: "unsupported",
            }
        )


@pytest.mark.parametrize("status", ["submitted", "rejected"])
def test_terminal_description_requires_a_bound_receipt_pair(status: str) -> None:
    with pytest.raises(ValidationError):
        NotificationSegmentResult.model_validate(
            {
                "company_id": command().company_id,
                "command": command(),
                "status": status,
                "observed_at": datetime.now(UTC),
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"receipt_id": UUID(int=9)},
        {"receipt_sha256": "a" * 64},
        {"observation_id": UUID(int=10), "observation_sha256": "b" * 64},
        {"company_id": UUID(int=99)},
        {"billing": "settled"},
        {"status": "completed"},
    ],
)
def test_partial_evidence_or_cross_company_and_completion_claims_deny(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NotificationSegmentResult.model_validate(
            {
                "company_id": command().company_id,
                "command": command(),
                "status": "blocked",
                "observed_at": datetime.now(UTC),
            }
            | changes
        )
