"""One issued SDK call, protected result recording and bounded capacity cleanup.

Unissued/duplicate callers do not release a competing caller's lease. The segment
owner handles that cleanup. Provider validity never publishes business completion.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime

from nexus.company.access import VerifiedIdentity
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    EndpointResolver,
    ModelRequestCancelledError,
)
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionState
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.model_authorizer import PersistentModelCallAuthorizer, RecordedModelOutcome
from nexus.harness.model_client_contracts import (
    GovernedModelCancelledError,
    GovernedModelResult,
    RecordingError,
    ReleaseError,
)

__all__ = ["GovernedModelCancelledError", "GovernedModelClient", "GovernedModelResult"]


class GovernedModelClient:
    """Server-only one-call composition; no default gate, retries, fallback or tools."""

    def __init__(
        self,
        registry: ModelRegistry,
        resolver: EndpointResolver,
        gate: PersistentModelCallAuthorizer,
        execution: ExecutionStore,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        *,
        cleanup_seconds: float = 5,
        model_observations: tuple[ModelEligibilityObservation, ...] = (),
    ) -> None:
        if gate is None or resolver is None or execution is None:
            raise ValueError("Trusted gate, resolver and execution store are required")
        if (
            isinstance(cleanup_seconds, bool)
            or not math.isfinite(cleanup_seconds)
            or not 0 < cleanup_seconds <= 5
            or lease.mode != "execute"
            or registry.company_id != lease.company_id
            or (identity.principal_id, identity.workspace_id)
            != (lease.actor_id, lease.workspace_id)
        ):
            raise ValueError("Server lease/identity or bounded cleanup configuration is invalid")
        gate.require_eligibility_configuration(registry, model_observations)
        self._adapter = CompanyModelAdapters(
            registry,
            resolver,
            gate,
            model_observations=model_observations,
            before_sdk=gate.revalidate_before_sdk,
        )
        self._gate, self._execution = gate, execution
        self._lease, self._identity = lease, identity
        self._cleanup_seconds, self._used = cleanup_seconds, False

    async def request_once(
        self, call: CompanyModelRequest, *, now: datetime
    ) -> GovernedModelResult:
        """Immediately settle issued output; denied callers cannot revoke another issuer."""
        if (
            self._used
            or call.tools
            or (call.company_id, call.task_id, call.trace_id, call.actor_id)
            != (
                self._lease.company_id,
                self._lease.task_id,
                self._lease.trace_id,
                self._lease.actor_id,
            )
        ):
            return self._outcome(
                CompanyModelResult(
                    request_id=call.request_id,
                    status="denied",
                    billing="not_issued",
                    error_code="duplicate_scope_or_tools_denied",
                )
            )
        self._used = True  # No await separates the one-time test and consumption.
        try:
            result = await self._adapter.request_once(call, now=now)
        except ModelRequestCancelledError as cancelled:
            raise GovernedModelCancelledError(await self._finish(call, cancelled.result)) from None
        if result.billing == "not_issued":
            return self._outcome(result)
        return await self._finish(call, result)

    async def _finish(
        self, call: CompanyModelRequest, result: CompanyModelResult
    ) -> GovernedModelResult:
        task = asyncio.create_task(self._settle(call, result))
        cancelled = False
        while True:  # The independently timed recording/release bound this wait.
            try:
                outcome = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                cancelled = True
                if task.cancelled():
                    outcome = self._outcome(result, recording_error="cleanup_interrupted")
                    break
        if cancelled:
            raise GovernedModelCancelledError(outcome) from None
        return outcome

    async def _settle(
        self, call: CompanyModelRequest, result: CompanyModelResult
    ) -> GovernedModelResult:
        recorded: RecordedModelOutcome | None = None
        recording_error: RecordingError | None = None
        try:
            async with asyncio.timeout(self._cleanup_seconds):
                recorded = await self._gate.record_result(call, result)
        except TimeoutError:
            recording_error = "recording_timeout"
        except ValueError:
            recording_error = "recording_denied"
        except Exception:
            recording_error = "recording_failed"
        state: ExecutionState | None = None
        release_error: ReleaseError | None = None
        try:
            async with asyncio.timeout(self._cleanup_seconds):
                state = (
                    await self._execution.release(
                        self._lease,
                        self._identity,
                        blocked=recorded is None or recorded.stop_required,
                    )
                ).state
        except TimeoutError:
            release_error = "release_timeout"
        except ValueError:
            release_error = "release_denied"
        except Exception:
            release_error = "release_failed"
        return self._outcome(result, recorded, recording_error, release_error, state)

    @staticmethod
    def _outcome(
        result: CompanyModelResult,
        recorded: RecordedModelOutcome | None = None,
        recording_error: RecordingError | None = None,
        release_error: ReleaseError | None = None,
        state: ExecutionState | None = None,
    ) -> GovernedModelResult:
        unissued = result.billing == "not_issued"
        return GovernedModelResult(
            provider_result=result,
            recorded=recorded,
            recording_status="recorded" if recorded else ("not_issued" if unissued else "failed"),
            recording_error=recording_error,
            ledger_billing=recorded.billing
            if recorded
            else ("not_issued" if unissued else "unconfirmed"),
            billing_limitation=(
                "none"
                if recorded and recorded.billing == "known"
                else "unreconciled_hold"
                if recorded
                else "unissued_no_receipt"
                if unissued
                else "ledger_unconfirmed"
            ),
            release_status="released"
            if state
            else ("failed" if release_error else "not_attempted"),
            release_error=release_error,
            execution_state=state,
            stop_required=recorded is None or recorded.stop_required or release_error is not None,
        )
