"""Typed output cannot conflate provider validity, ledger billing and company completion."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.core.llm.company_adapter_contracts import CompanyModelResult
from nexus.harness.model_client import GovernedModelCancelledError, GovernedModelResult


def unconfirmed() -> GovernedModelResult:
    return GovernedModelResult(
        provider_result=CompanyModelResult(
            request_id=UUID(int=7), status="failed", billing="unknown", error_code="timeout"
        ),
        recorded=None,
        recording_status="failed",
        recording_error="recording_denied",
        ledger_billing="unconfirmed",
        billing_limitation="ledger_unconfirmed",
        release_status="failed",
        release_error="release_denied",
        stop_required=True,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"ledger_billing": "known"},
        {"recording_status": "recorded"},
        {"recording_error": None},
        {"billing_limitation": "none"},
        {"release_status": "released"},
        {"release_error": None},
        {"execution_state": "verifying"},
        {"stop_required": False},
        {"company_completed": True},
        {"release_error": "credential-containing-free-text"},
    ],
)
def test_unconfirmed_output_cannot_assert_ledger_capacity_or_completion(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GovernedModelResult.model_validate(unconfirmed().model_dump() | change)


def test_cancellation_preserves_provider_and_recording_diagnostics() -> None:
    result = unconfirmed()
    error = GovernedModelCancelledError(result)
    assert error.result == result.provider_result and error.governed == result
    assert isinstance(error, BaseException) and not isinstance(error, Exception)
