"""Real recovery orchestration with supplied SQL/source/prepared-read delivery only."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.execution.planning_preparation_recovery import (
    RecoveredPlanningWait,
    recover_prepared_wait,
)
from nexus.execution.runtime_support import snapshot
from nexus.tests.unit.nexus_report_fixture import credentials
from nexus.tests.unit.planning_recovery_fixture import (
    RecoveryCase,
    install_recovery_delivery,
    recovery_case,
)
from nexus.tests.unit.test_planning_prepared_store import setup
from nexus.tests.unit.test_planning_services import services


async def test_pending_graph_resources_and_original_end_prevent_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    check = (await recovery_case(tmp_path)).check
    check.require_current()
    entered = asyncio.Event()
    owner = asyncio.create_task(entered.wait())
    check.services.prepared._owners.append(cast(asyncio.Task[object], owner))
    try:
        with pytest.raises(ValueError, match="resources"):
            check.require_current()
    finally:
        entered.set()
        await owner
    check.operation.end = clock_us() - 1
    with pytest.raises(TimeoutError):
        check.require_current()
    check.operation.finish()


async def test_unconfigured_company_cannot_gain_recovery_or_a_fresh_actor_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = services(tmp_path)
    f = setup(tmp_path / "fixture", monkeypatch)
    owner_binding = f.current.child.binding.model_copy(update={"actor_id": f.owner.principal_id})
    owner = await credentials(owner_binding).current(owner_binding)
    current = AsyncMock(side_effect=AssertionError("Unconfigured recovery cannot read actor token"))
    monkeypatch.setattr(type(configured.identities), "current", current)
    with pytest.raises(ValueError):
        await recover_prepared_wait(
            configured,
            f.scope,
            owner,
            f.prepared.request.action_id,
            "a" * 64,
            expected_goal=f.prepared.binding.goal,
            expected_current_revision_id=UUID(int=40),
            end_us=clock_us() + 30_000_000,
        )
    current.assert_not_awaited()
    assert not configured._operations and datetime.now(UTC) < owner.expires_at


async def invoke(case: RecoveryCase) -> RecoveredPlanningWait:
    check = case.check
    return await recover_prepared_wait(
        check.services,
        check.owner_scope,
        check.owner,
        check.action.proposal.action_id,
        check.action.proposal_hash,
        expected_goal=check.expected_goal,
        expected_current_revision_id=check.expected_head,
        end_us=clock_us() + 30_000_000,
    )


async def test_full_driver_restores_exact_wait_and_replay_does_not_create_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    delivery = install_recovery_delivery(case, monkeypatch)
    resolver = AsyncMock(side_effect=AssertionError("Wait recovery cannot resolve a model key"))
    monkeypatch.setattr(case.check.services.resolver, "resolve", resolver)
    before = snapshot(case.value.work)
    result = await invoke(case)
    assert result.value.work.state == "awaiting_approval"
    assert result.value.work.fence == before.fence + 1
    assert result.value.work.counters == before.counters
    assert result.value.work.segment_number == before.segment_number
    assert result.value.action == case.check.action
    assert result.value.reference == case.check.loaded.reference
    assert result.value.company_completed is False
    assert result.read_end_us <= case.check.loaded.read_end_us
    assert delivery.fake.flush.await_count == 1
    replay = await invoke(case)
    assert replay.value == result.value
    assert delivery.fake.flush.await_count == 1
    assert not case.check.services.pending_owners() and not case.check.services._operations
    delivery.fake.add.assert_not_called()
    resolver.assert_not_awaited()


async def test_native_change_during_prepared_read_denies_before_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    delivery = install_recovery_delivery(case, monkeypatch)

    def changed() -> None:
        case.value.work.fence += 1

    delivery.after_load = changed
    with pytest.raises(ValueError, match="snapshot changed"):
        await invoke(case)
    assert case.value.work.state == "running"
    delivery.fake.flush.assert_not_awaited()
    assert delivery.rollbacks == 1


async def test_first_static_window_is_not_renewed_by_later_source_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    delivery = install_recovery_delivery(case, monkeypatch)
    before = snapshot(case.value.work)
    delivery.first_static_until = case.value.now + timedelta(milliseconds=80)
    delivery.load_delay = 0.15
    with pytest.raises(TimeoutError):
        await invoke(case)
    assert snapshot(case.value.work) == before
    delivery.fake.flush.assert_not_awaited()
    # The actual slow coroutine survives the denied caller; only settlement is adopted.
    pending = case.check.services.pending_owners()
    assert pending
    await asyncio.gather(*pending)
    assert not case.check.services.pending_owners()
    assert snapshot(case.value.work) == before


async def test_cancelled_driver_retains_actual_read_and_never_adopts_late_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    delivery = install_recovery_delivery(case, monkeypatch)
    delivery.load_gate = asyncio.Event()
    assert delivery.load_started is not None
    before = snapshot(case.value.work)
    request = asyncio.create_task(invoke(case))
    await asyncio.wait_for(delivery.load_started.wait(), timeout=3)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    pending = case.check.services.pending_owners()
    assert pending and snapshot(case.value.work) == before
    delivery.fake.flush.assert_not_awaited()
    delivery.load_gate.set()
    await asyncio.gather(*pending)
    assert not case.check.services.pending_owners()
    assert snapshot(case.value.work) == before


async def test_cancelled_native_transition_settles_before_supplied_transaction_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    delivery = install_recovery_delivery(case, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    before = snapshot(case.value.work)

    async def slow_flush() -> None:
        entered.set()
        await release.wait()

    delivery.fake.flush.side_effect = slow_flush
    request = asyncio.create_task(invoke(case))
    await asyncio.wait_for(entered.wait(), timeout=3)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    pending = case.check.services.pending_owners()
    assert pending and delivery.active == 1
    assert delivery.commits == 1  # Initial metadata transaction only.
    release.set()
    await asyncio.gather(*pending, return_exceptions=True)
    assert not case.check.services.pending_owners()
    assert delivery.rollbacks == 1 and delivery.active == 0
    assert delivery.commits == 1 and snapshot(case.value.work) == before


async def test_missing_original_caller_end_rejects_before_any_actor_or_native_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    check = case.check
    check.operation.finish()
    current = AsyncMock(side_effect=AssertionError("Expired request cannot obtain an actor"))
    monkeypatch.setattr(type(check.services.identities), "current", current)
    with pytest.raises(TimeoutError):
        await recover_prepared_wait(
            check.services,
            check.owner_scope,
            check.owner,
            check.action.proposal.action_id,
            check.action.proposal_hash,
            expected_goal=check.expected_goal,
            expected_current_revision_id=check.expected_head,
            end_us=0,
        )
    current.assert_not_awaited()
