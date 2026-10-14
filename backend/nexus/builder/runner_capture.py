"""Known bounded frame decoding and actual M1 renewal; missing facts remain unknown."""

from __future__ import annotations

import tarfile
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.native_state import current_source
from nexus.builder.process import ProcessCapture
from nexus.builder.result_codec import captured, decode_runtime
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash


class LeaseWatch:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        execution: ExecutionStore,
        identity: VerifiedIdentity,
        action: ActionProposal,
        guard: BuilderSourceGuard,
    ) -> None:
        self.factory, self.execution, self.identity, self.action, self.guard = (
            factory,
            execution,
            identity,
            action,
            guard,
        )
        self.last_renewed = monotonic()

    async def check(self) -> None:
        if monotonic() - self.last_renewed >= 10:
            self.guard.lease = await self.execution.renew(
                self.guard.lease, self.identity, ttl_seconds=60
            )
            self.last_renewed = monotonic()
        await current_source(
            self.factory, self.guard.lease, self.identity, self.action, self.guard, issued=True
        )


def capture_result(
    capture: ProcessCapture,
    spec: BuilderExecutionSpec,
    action: ActionProposal,
    fence: int,
    image_id: str,
    name: str,
) -> BuilderRunResult:
    reason = capture.interruption or ("runtime_envelope_failed" if capture.exit_code != 0 else None)
    if reason is None:
        try:
            return decode_runtime(
                capture.stdout,
                spec,
                action_hash(action),
                fence,
                image_id,
                name,
                datetime.now(UTC),
                capture.elapsed_millis,
            )
        except (ValueError, tarfile.TarError, IndexError):
            reason = "runtime_envelope_invalid"
    return BuilderRunResult(
        spec=spec,
        proposal_sha256=action_hash(action),
        intent_fence=fence,
        image_id=image_id,
        container_name=name,
        outcome="outcome_unknown",
        recorded_at=datetime.now(UTC),
        elapsed_millis=capture.elapsed_millis,
        logs=(captured("logs/runtime.err", capture.stderr),) if capture.stderr else (),
        limitations=(reason, "business_readiness_unproven"),
    )
