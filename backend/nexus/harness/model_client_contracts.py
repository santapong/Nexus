"""Provider evidence, ledger confirmation and cleanup are distinct typed outcomes."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from nexus.core.llm.company_adapter_contracts import CompanyModelResult, ModelRequestCancelledError
from nexus.execution.runtime_contracts import ExecutionState
from nexus.harness.model_authorizer import RecordedModelOutcome

RecordingError = Literal[
    "recording_denied", "recording_failed", "recording_timeout", "cleanup_interrupted"
]
ReleaseError = Literal["release_denied", "release_failed", "release_timeout"]


class GovernedModelResult(BaseModel):
    """Provider validity cannot assert ledger billing, released capacity or completion."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["nexus.company.model-client.v1"] = "nexus.company.model-client.v1"
    provider_result: CompanyModelResult
    recorded: RecordedModelOutcome | None
    recording_status: Literal["recorded", "not_issued", "failed"]
    recording_error: RecordingError | None = None
    ledger_billing: Literal["known", "unknown", "unconfirmed", "not_issued"]
    billing_limitation: Literal[
        "none", "unissued_no_receipt", "unreconciled_hold", "ledger_unconfirmed"
    ]
    release_status: Literal["released", "not_attempted", "failed"]
    release_error: ReleaseError | None = None
    execution_state: ExecutionState | None = None
    stop_required: bool
    company_completed: Literal[False] = False

    @model_validator(mode="after")
    def honest_recording(self) -> Self:
        """Unconfirmed wire usage and unavailable capacity never become ledger facts."""
        if (self.recording_status == "recorded") != (self.recorded is not None):
            raise ValueError("Recording status requires its actual persistent outcome")
        unissued = self.provider_result.billing == "not_issued"
        expected = (
            self.recorded.billing
            if self.recorded
            else ("not_issued" if unissued else "unconfirmed")
        )
        if self.ledger_billing != expected or (unissued and self.recorded is not None):
            raise ValueError("Ledger billing differs from actual recording confirmation")
        if self.recorded and self.recorded.billing != self.provider_result.billing:
            raise ValueError("Recorded billing differs from preserved provider evidence")
        if (
            self.recorded
            and self.recorded.billing == "known"
            and (self.recorded.actual_usd is None or self.recorded.receipt_id is None)
        ):
            raise ValueError("Known ledger billing needs actual cost and a receipt")
        limitation = {
            "known": "none",
            "unknown": "unreconciled_hold",
            "not_issued": "unissued_no_receipt",
            "unconfirmed": "ledger_unconfirmed",
        }[self.ledger_billing]
        if self.billing_limitation != limitation:
            raise ValueError("Billing limitation must describe ledger confirmation")
        if (self.recording_status == "failed") != (self.recording_error is not None):
            raise ValueError("Recording failure needs a fixed diagnostic code")
        if (self.release_status == "released") != (self.execution_state is not None):
            raise ValueError("Released capacity needs the actual persistent state")
        if (self.release_status == "failed") != (self.release_error is not None):
            raise ValueError("Release failure needs a fixed diagnostic code")
        if not self.stop_required and (
            self.recorded is None or self.recorded.stop_required or self.release_error is not None
        ):
            raise ValueError("Unconfirmed or blocked work must stop")
        return self


class GovernedModelCancelledError(ModelRequestCancelledError):
    """Cancellation propagates with original provider evidence and cleanup diagnostics."""

    def __init__(self, governed: GovernedModelResult) -> None:
        self.governed = governed.model_copy(update={"stop_required": True})
        super().__init__(governed.provider_result)
        self.args = ("Governed model call cancelled; inspect preserved outcomes",)
