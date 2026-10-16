"""One issued SDK call, protected result recording and bounded capacity cleanup.

Unissued/duplicate callers do not release a competing caller's lease. The segment
owner handles that cleanup. Provider validity never publishes business completion.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime
from typing import cast

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
        end_us: int | None = None,
        sdk_end_us: int | None = None,
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
        anchor = time.monotonic_ns() // 1000
        if end_us is not None and (type(end_us) is not int or end_us <= anchor):
            raise ValueError("Original model operation end is invalid or expired")
        if sdk_end_us is not None and (
            type(sdk_end_us) is not int or end_us is None or not anchor < sdk_end_us <= end_us
        ):
            raise ValueError("Original SDK end cannot extend its operation")
        lease_end = anchor + int(
            (lease.expires_at - datetime.now(lease.expires_at.tzinfo)).total_seconds() * 1_000_000
        )
        self._end_us = min(end_us, lease_end) if end_us is not None else None
        self._adapter = CompanyModelAdapters(
            registry,
            resolver,
            gate,
            model_observations=model_observations,
            before_sdk=gate.revalidate_before_sdk,
            operation_deadline=lease.expires_at,
            operation_end_us=min(sdk_end_us, self._end_us)
            if sdk_end_us is not None and self._end_us is not None
            else self._end_us,
        )
        self._gate, self._execution = gate, execution
        self._lease, self._identity = lease, identity
        self._cleanup_seconds, self._used = cleanup_seconds, False
        self._owners: list[asyncio.Task[object]] = []
        self._first_error: BaseException | None = None

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual native/filesystem/SDK cleanup owners; never a positive outcome flag."""
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self._owners if not task.done() or task.cancelled()),
                    *self._gate.pending_owners(),
                    *self._adapter.pending_owners(),
                )
            )
        )

    def request_stop(self) -> None:
        """Latch pre-SDK denial; never cancel an actual SDK/native/filesystem leaf."""
        self._adapter.request_stop()

    def _remaining(self) -> float:
        return (
            min(
                self._cleanup_seconds,
                max(0, self._end_us - time.monotonic_ns() // 1000) / 1_000_000,
            )
            if self._end_us is not None
            else self._cleanup_seconds
        )

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
            self._first_error = self._first_error or cancelled
            error = GovernedModelCancelledError(await self._finish(call, cancelled.result))
            error.__dict__["_nexus_model_first"] = cancelled
            error.__dict__["_nexus_model_pending"] = self.pending_owners()
            raise error from None
        except BaseException as first:
            self._first_error = self._first_error or first
            self.request_stop()
            first.__dict__["_nexus_model_pending"] = self.pending_owners()
            raise
        if result.billing == "not_issued":
            return self._outcome(result)
        return await self._finish(call, result)

    async def _finish(
        self, call: CompanyModelRequest, result: CompanyModelResult
    ) -> GovernedModelResult:
        task = asyncio.create_task(self._settle(call, result))
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        first: asyncio.CancelledError | None = None
        while True:  # The independently timed recording/release bound this wait.
            try:
                outcome = await asyncio.shield(task)
                break
            except asyncio.CancelledError as cancelled:
                self.request_stop()
                self._first_error = self._first_error or cancelled
                first = first or cancelled
                if task.cancelled():
                    outcome = self._outcome(result, recording_error="cleanup_interrupted")
                    break
        if first is not None:
            error = GovernedModelCancelledError(outcome)
            error.__dict__["_nexus_model_first"] = first
            error.__dict__["_nexus_model_pending"] = self.pending_owners()
            raise error from None
        return outcome

    async def _settle(
        self, call: CompanyModelRequest, result: CompanyModelResult
    ) -> GovernedModelResult:
        recorded: RecordedModelOutcome | None = None
        recording_error: RecordingError | None = None
        if self._remaining() <= 0:
            return self._outcome(
                result, recording_error="recording_timeout", release_error="release_timeout"
            )
        try:
            async with asyncio.timeout(self._remaining()):
                recorded = await self._gate.record_result(call, result)
        except TimeoutError as error:
            self._first_error = self._first_error or error
            recording_error = "recording_timeout"
        except ValueError as error:
            self._first_error = self._first_error or error
            recording_error = "recording_denied"
        except Exception as error:
            self._first_error = self._first_error or error
            recording_error = "recording_failed"
        state: ExecutionState | None = None
        release_error: ReleaseError | None = None
        if self._gate.pending_owners() or self._adapter.pending_owners():
            # A timed-out recording chain never resumes; resource retirement alone
            # cannot confirm a receipt or free capacity while the original IO runs.
            return self._outcome(result, recorded, recording_error, "release_failed")
        if self._remaining() <= 0:
            return self._outcome(result, recorded, recording_error, "release_timeout")
        release = asyncio.create_task(
            self._execution.release(
                self._lease,
                self._identity,
                blocked=recorded is None or recorded.stop_required,
            )
        )
        self._owners.append(cast(asyncio.Task[object], release))
        release.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(self._remaining()):
                state = (await asyncio.shield(release)).state
        except TimeoutError as error:
            self._first_error = self._first_error or error
            release_error = "release_timeout"
        except ValueError as error:
            self._first_error = self._first_error or error
            release_error = "release_denied"
        except Exception as error:
            self._first_error = self._first_error or error
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
