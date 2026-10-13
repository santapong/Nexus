"""Offline worker evidence never treats forged envelopes as issued outcomes."""

from __future__ import annotations

from uuid import UUID

import pytest

from nexus.execution.company_worker_contracts import OfflineOutput, WorkerResult
from nexus.tests.unit.test_company_foundation import COMPANY, NOW, TASK, TRACE, proposal


def output() -> OfflineOutput:
    return OfflineOutput(
        company_id=COMPANY,
        action_id=proposal().action_id,
        task_id=TASK,
        trace_id=TRACE,
        proposal_hash="a" * 64,
        tool="fake.internal.draft.v1",
        tool_version="v1",
        output="Synthetic offline result",
        model_requests=1,
        tool_attempts=1,
        recorded_at=NOW,
    )


def test_evidence_envelope_checks_exact_command_scope_and_proposal() -> None:
    current = output()
    current.require_binding(COMPANY, TASK, TRACE, proposal().action_id, "a" * 64)
    for company, task, trace, action, digest in (
        (UUID(int=999), TASK, TRACE, proposal().action_id, "a" * 64),
        (COMPANY, UUID(int=999), TRACE, proposal().action_id, "a" * 64),
        (COMPANY, TASK, UUID(int=999), proposal().action_id, "a" * 64),
        (COMPANY, TASK, TRACE, UUID(int=999), "a" * 64),
        (COMPANY, TASK, TRACE, proposal().action_id, "b" * 64),
    ):
        with pytest.raises(ValueError):
            current.require_binding(company, task, trace, action, digest)


def test_worker_result_never_claims_business_completion() -> None:
    result = WorkerResult(
        company_id=COMPANY,
        task_id=TASK,
        action_id=proposal().action_id,
        segment_id=UUID(int=900),
        status="verifying",
        receipt_id=UUID(int=901),
        limitations=("Independent acceptance has not run",),
    )
    payload: dict[str, object] = result.model_dump(mode="json")
    assert payload["status"] != "completed"
    assert payload["status"] == "verifying"
    with pytest.raises(ValueError):
        WorkerResult.model_validate(payload | {"status": "completed"})
