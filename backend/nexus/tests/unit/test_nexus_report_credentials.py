"""Actual JWT verification and retained native-claim tasks; no DB/provider/native execution."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.nexus_report_auth import acquire_nexus_report
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.unit.nexus_intent_fixture import boundary
from nexus.tests.unit.nexus_report_fixture import credentials, services


async def test_matching_real_credential_clamps_original_claim_and_denies_missing_or_crossed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = boundary(3)
    effects = value.install(monkeypatch)
    configured = services(value, effects)
    admission = value.catalog.nexus_cycle_admission
    assert admission is not None
    binding = admission.slots[3].child.binding
    command = SegmentCommand(
        company_id=value.work.company_id,
        task_id=value.work.task_id,
        trace_id=value.work.trace_id,
        actor_id=value.work.actor_id,
        workspace_id=value.work.workspace_id,
        run_id=value.work.run_id,
        action_id=value.action.id,
        segment_id=value.lease.segment_id,
    )
    scope = LedgerScope(
        company_id=binding.company_id,
        principal_id=binding.actor_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
    )
    action = ActionProposal.model_validate_json(value.action.proposal_json)
    calls = []

    async def claim(*args: object, ttl_seconds: int, **kwargs: object) -> ExecutionLease:
        calls.append(ttl_seconds)
        return value.lease.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(seconds=ttl_seconds)}
        )

    monkeypatch.setattr(configured.execution, "recover_dispatched", claim)
    short = replace(
        configured,
        report_credentials=(
            (binding, credentials(binding, seconds=5)),
            configured.report_credentials[1],
        ),
    )
    context = await acquire_nexus_report(short, command, action, value.identity, binding, scope)
    assert context.credential is not None and 1 <= calls[0] <= 5
    assert (
        context.lease.expires_at <= context.credential.expires_at
        and context.identity == value.identity
    )
    assert not configured.pending_owners()
    for sources in (
        (),
        ((binding, credentials(binding, foreign=True)), configured.report_credentials[1]),
        ((binding, credentials(binding, seconds=-1)), configured.report_credentials[1]),
    ):
        with pytest.raises(ValueError):
            await acquire_nexus_report(
                replace(configured, report_credentials=sources),
                command,
                action,
                value.identity,
                binding,
                scope,
            )
    assert len(calls) == 1


async def test_cancelled_claim_remains_owned_then_releases_only_actual_returned_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = boundary(3)
    configured = services(value, value.install(monkeypatch))
    admission = value.catalog.nexus_cycle_admission
    assert admission is not None
    binding = admission.slots[3].child.binding
    command = SegmentCommand(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        action_id=value.action.id,
        segment_id=value.lease.segment_id,
    )
    scope = LedgerScope(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        principal_id=binding.actor_id,
    )
    entered, finish = asyncio.Event(), asyncio.Event()

    async def claim(*args: object, **kwargs: object) -> ExecutionLease:
        entered.set()
        await finish.wait()
        return value.lease

    release = AsyncMock()
    monkeypatch.setattr(configured.execution, "recover_dispatched", claim)
    monkeypatch.setattr(configured.execution, "release", release)
    caller = asyncio.create_task(
        acquire_nexus_report(
            configured,
            command,
            ActionProposal.model_validate_json(value.action.proposal_json),
            value.identity,
            binding,
            scope,
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    caller.cancel("original caller")
    with pytest.raises(asyncio.CancelledError, match="original caller"):
        await caller
    assert configured.pending_owners() and all(
        not task.cancelled() for task in configured.pending_owners()
    )
    release.assert_not_awaited()
    finish.set()
    _, pending = await asyncio.wait(configured.pending_owners(), timeout=2)
    assert not pending
    release.assert_awaited_once_with(value.lease, value.identity)
