"""Actual sealed expiry before/after intent preserves finite issuance and costs."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.process import ProcessCapture, bounded_call
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.engineering_worker import execute_engineering_segment
from nexus.execution.engineering_worker_identity import EngineeringCredentialSourceGuard
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_pending_services import pending_services
from nexus.tests.engineering_recovery_fixture import (
    engineering_recovery_factory as engineering_recovery_factory,
)
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_engineering_worker_replay import actual_command


@pytest.mark.parametrize("phase", ["before_intent", "after_intent"])
async def test_expired_sealed_credential_blocks_actual_fresh_native_issuance(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    # This >50-line test keeps actual public setup, one nominated expiry barrier
    # and native intent/hold/counter conservation in the same fixture occurrence.
    import nexus.builder.runner as module

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True, defer_verifier=True
    )
    services = pending_services(item, credential_seconds=3)
    command = await actual_command(engineering_recovery_factory, item.verifier_spec.job.action_id)
    calls, barriers = 0, 0
    original_prepare, original_invoke, original_call = (
        item.runner.prepare,
        item.runner.invoke,
        bounded_call,
    )

    async def expire(guard: BuilderSourceGuard) -> None:
        nonlocal barriers
        barriers += 1
        assert isinstance(guard, EngineeringCredentialSourceGuard)
        deadline = guard.credential.expires_at
        await asyncio.sleep(max(0, (deadline - datetime.now(UTC)).total_seconds()) + 0.03)

    async def prepare(spec: BuilderExecutionSpec, guard: BuilderSourceGuard) -> Path:
        root = await original_prepare(spec, guard)
        if phase == "before_intent":
            await expire(guard)
        return root

    async def invoke(
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action: ActionProposal,
        spec: BuilderExecutionSpec,
        guard: BuilderSourceGuard,
        base: Path,
    ) -> BuilderRunResult:
        if phase == "after_intent":
            await expire(guard)
        return await original_invoke(lease, identity, action, spec, guard, base)

    async def counted(*args: Any, **kwargs: Any) -> ProcessCapture:
        # Test-only passthrough mirrors the unchanged coroutine's arbitrary call arguments.
        nonlocal calls
        calls += 1
        return await original_call(*args, **kwargs)

    monkeypatch.setattr(item.runner, "prepare", prepare)
    monkeypatch.setattr(item.runner, "invoke", invoke)
    monkeypatch.setattr(module, "bounded_call", counted)
    result = await execute_engineering_segment(services, command, workflow_id=command.workflow_id)
    assert barriers == 1 and calls == 0 and result.acceptance_id is None
    assert result.status == ("blocked" if phase == "before_intent" else "outcome_unknown")
    async with engineering_recovery_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = await session.get(ExecutionWork, (COMPANY, command.task_id))
        intent = await session.get(EffectIntent, (COMPANY, command.action_id))
        hold = await session.get(CostHold, command.action_id)
        assert work is not None and work.worker_id is None and work.model_requests_used == 0
        assert work.tool_attempts_used == (0 if phase == "before_intent" else 1)
        assert hold is not None and hold.amount_usd > 0 and hold.actual_usd is None
        assert hold.state == ("held" if phase == "before_intent" else "unknown")
        assert (
            intent is None
            if phase == "before_intent"
            else intent is not None and intent.state == "outcome_unknown"
        )
