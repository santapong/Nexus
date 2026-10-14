"""Trusted process instrumentation observes delegated completion and never creates authority."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.execution.runtime_contracts import EffectRecord, EffectStart
from nexus.tests.notification_durable_unit_fixture import recovery_inputs
from nexus.tests.notification_process_wrappers import (
    InstrumentedNotificationEffects,
    NotificationProcessBarrier,
)


@pytest.mark.parametrize("permitted", [False, True])
async def test_only_delegated_new_committed_intent_emits_intent_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    permitted: bool,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    base = value.services.dispatcher.managed_effects
    store = InstrumentedNotificationEffects(
        value.services.reads.factory,
        value.services.reads.drafts,
        value.services.reads.facts.catalog,
        value.services.reads.facts.artifacts,
        value.services.reads.facts.freshness,
        policy=base.preparation.policy,
    )
    store.barrier = NotificationProcessBarrier(tmp_path, None)
    observed = AsyncMock()
    monkeypatch.setattr(store.barrier, "checkpoint", observed)
    record = EffectRecord(
        company_id=value.command.company_id,
        action_id=value.command.action_id,
        task_id=value.command.task_id,
        trace_id=value.command.trace_id,
        run_id=value.command.run_id,
        proposal_hash="a" * 64,
        intent_fence=1,
        attempt_kind="tool_attempts",
        state="intent",
        created_at=value.lease.expires_at,
        receipt=None,
        verification=None,
    )
    start = EffectStart(record=record, permit_external_call=permitted)
    delegated = AsyncMock(return_value=start)
    monkeypatch.setattr(ManagedNotificationEffectStore, "begin", delegated)
    result = await store.begin(value.lease, value.guard.witness.identity, value.command.action_id)
    assert result is start and delegated.await_count == 1
    assert observed.await_count == int(permitted)
    if permitted:
        assert observed.await_args is not None and observed.await_args.args[0] == "intent"


async def test_failed_delegated_commit_cannot_emit_a_successful_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await recovery_inputs(tmp_path, monkeypatch)
    base = value.services.dispatcher.managed_effects
    store = InstrumentedNotificationEffects(
        value.services.reads.factory,
        value.services.reads.drafts,
        value.services.reads.facts.catalog,
        value.services.reads.facts.artifacts,
        value.services.reads.facts.freshness,
        policy=base.preparation.policy,
    )
    store.barrier = NotificationProcessBarrier(tmp_path, None)
    marker = AsyncMock()
    monkeypatch.setattr(store.barrier, "checkpoint", marker)
    monkeypatch.setattr(
        ManagedNotificationEffectStore, "begin", AsyncMock(side_effect=ValueError("rollback"))
    )
    with pytest.raises(ValueError, match="rollback"):
        await store.begin(value.lease, value.guard.witness.identity, UUID(int=1))
    marker.assert_not_awaited()
