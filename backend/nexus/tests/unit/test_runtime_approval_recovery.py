"""Closed unissued-prefix checks with real ORM contracts and supplied SQL delivery."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.planning_prepared_contracts import (
    descriptor_for,
    descriptor_reference,
    encode_prepared,
)
from nexus.core.llm.company_pricing import quote_cost
from nexus.execution.planning_preparation_recovery import PreparedWaitRecovery
from nexus.execution.runtime_approval_recovery import require_unissued_pending, restore_wait_locked
from nexus.execution.runtime_contracts import ExecutionRegistration
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.unit.planning_recovery_fixture import RecoveryCase, recovery_case
from nexus.tests.unit.test_planning_prepared_store import pending, setup


def prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AsyncSession, CompanyControl, ExecutionWork, JournalAction, datetime]:
    """No database, witness mint or actual native transition is represented by this fixture."""
    f = setup(tmp_path, monkeypatch)
    work = cast(ExecutionWork, f.rows[ExecutionWork])
    registration = ExecutionRegistration.model_validate_json(work.registration_json).model_copy(
        update={"workflow_name": "company.planning.v1", "workflow_version": "v1"}
    )
    work.workflow_name = registration.workflow_name
    work.workflow_version = registration.workflow_version
    work.segment_id = uuid5(work.run_id, "nexus-execution-segment-v1:1")
    work.registration_json = registration.model_dump_json()
    work.registration_hash = registration_digest(registration)
    _, body = encode_prepared(f.prepared)
    reference, _ = descriptor_reference(
        descriptor_for(
            f.prepared,
            body,
            run_id=work.run_id,
            registration_sha256=work.registration_hash,
            owner_id=f.owner.principal_id,
        )
    )
    pending(f, reference)
    row = cast(JournalAction, f.rows[JournalAction])
    now = datetime.now(UTC)
    work.lease_until = now - timedelta(seconds=1)
    control = CompanyControl(
        company_id=work.company_id,
        owner_id=f.owner.principal_id,
        policy_version="policy-v1",
        price_version=f.prepared.request.price_version,
        paused=False,
    )
    result = MagicMock()
    result.all.return_value = [row]
    fake = MagicMock(spec=AsyncSession)
    fake.in_transaction.return_value = True
    fake.scalars = AsyncMock(return_value=result)
    fake.scalar = AsyncMock(return_value=None)
    return cast(AsyncSession, fake), control, work, row, now


@pytest.mark.parametrize("state", ["running", "blocked", "awaiting_approval"])
async def test_exact_zero_issued_prefix_or_owner_wait_is_read_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    session, control, work, action, now = prefix(tmp_path, monkeypatch)
    work.state = state
    if state != "running":
        work.worker_id = work.lease_until = work.lease_mode = work.lease_principal_id = None
    if state == "awaiting_approval":
        work.waiting_action_id = action.id
    before = snapshot(work)
    record = await require_unissued_pending(
        session, control, work, action.id, action.proposal_hash, now
    )
    assert record.proposal.action_id == action.id and snapshot(work) == before
    cast(MagicMock, session).flush.assert_not_called()
    cast(MagicMock, session).add.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "live",
        "partial",
        "reconcile",
        "waiting-other",
        "eligible",
        "used",
        "delegated",
        "ambiguous",
        "wrong-hash",
        "consumed",
        "authorized",
        "attempt",
        "intent",
        "hold",
        "dispatch",
    ],
)
async def test_any_live_ambiguous_changed_or_issued_prefix_stays_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    session, control, work, action, now = prefix(tmp_path, monkeypatch)
    fake = cast(MagicMock, session)
    expected_hash = action.proposal_hash
    if fault == "live":
        work.lease_until = now + timedelta(seconds=5)
    elif fault == "partial":
        work.worker_id = None
    elif fault == "reconcile":
        work.lease_mode = "reconcile"
    elif fault == "waiting-other":
        work.waiting_action_id = UUID(int=999)
    elif fault == "eligible":
        work.state = "eligible"
    elif fault == "used":
        work.model_requests_used = 1
    elif fault == "delegated":
        work.tool_attempts_delegated = 1
    elif fault == "ambiguous":
        fake.scalars.return_value.all.return_value = [action, action]
    elif fault == "wrong-hash":
        expected_hash = "f" * 64
    elif fault == "consumed":
        action.consumed_at = now
    elif fault == "authorized":
        action.state = "authorized"
    else:
        position = ["attempt", "intent", "hold", "dispatch"].index(fault)
        fake.scalar.side_effect = [None] * position + [UUID(int=999)]
    before = snapshot(work)
    with pytest.raises(ValueError):
        await require_unissued_pending(session, control, work, action.id, expected_hash, now)
    assert snapshot(work) == before
    fake.flush.assert_not_called()


@pytest.mark.parametrize("fault", [None, "expired", "rejected", "other-owner", "other-hash"])
async def test_original_owner_decision_is_preserved_or_denied_without_renewal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    session, control, work, action, now = prefix(tmp_path, monkeypatch)
    decision = ApprovalDecision(
        company_id=work.company_id,
        decision_id=UUID(int=500),
        action_id=action.id,
        action_revision=1,
        action_hash=action.proposal_hash,
        approver_id=control.owner_id,
        decision="rejected" if fault == "rejected" else "approved",
        issued_at=now - timedelta(seconds=10),
        expires_at=now + timedelta(seconds=-1 if fault == "expired" else 10),
    )
    if fault == "other-owner":
        decision = decision.model_copy(update={"approver_id": UUID(int=999)})
    if fault == "other-hash":
        decision = decision.model_copy(update={"action_hash": "f" * 64})
    action.approval_json = decision.model_dump_json()
    original = action.approval_json
    if fault is None:
        result = await require_unissued_pending(
            session, control, work, action.id, action.proposal_hash, now
        )
        assert result.approval == decision
    else:
        with pytest.raises(ValueError):
            await require_unissued_pending(
                session, control, work, action.id, action.proposal_hash, now
            )
    assert action.approval_json == original and action.consumed_at is None


def native_writer(
    case: RecoveryCase, monkeypatch: pytest.MonkeyPatch
) -> tuple[AsyncSession, MagicMock]:
    """The writer is real; its SQL transport and separately tested source check are supplied."""
    import nexus.execution.runtime_approval_recovery as module

    value, check = case.value, case.check
    fake = MagicMock(spec=AsyncSession)
    fake.in_transaction.return_value = True
    result = MagicMock()
    result.all.return_value = [value.action]
    fake.scalars = AsyncMock(return_value=result)
    fake.scalar = AsyncMock(return_value=None)
    fake.flush = AsyncMock()
    price = value.catalog.models.models[0].price
    assert price is not None
    quote = quote_cost(price, check.loaded.prepared.request.bounds, now=value.now)
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=value.now))
    monkeypatch.setattr(PreparedWaitRecovery, "validate_locked", AsyncMock(return_value=quote))
    return cast(AsyncSession, fake), fake


async def test_writer_restores_only_wait_and_exact_replay_keeps_fence_and_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    value, check = case.value, case.check
    session, fake = native_writer(case, monkeypatch)
    before = snapshot(value.work)
    original_action = value.action.proposal_json, value.action.approval_json
    try:
        restored = await restore_wait_locked(
            check.services.execution, session, value.control, value.work, check
        )
        assert restored.value.work.state == "awaiting_approval"
        assert restored.value.work.waiting_action_id == value.action.id
        assert restored.value.work.worker_id is None
        assert restored.value.work.counters == before.counters
        assert restored.value.work.segment_number == before.segment_number
        assert restored.value.work.fence == before.fence + 1
        assert (value.action.proposal_json, value.action.approval_json) == original_action
        assert value.action.consumed_at is None
        assert fake.flush.await_count == 1
        second = replace(check, initial=snapshot(value.work))
        replay = await restore_wait_locked(
            check.services.execution, session, value.control, value.work, second
        )
        assert replay == restored
        assert fake.flush.await_count == 1
        fake.add.assert_not_called()
    finally:
        check.operation.finish()


async def test_changed_native_snapshot_denies_before_recovery_reads_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await recovery_case(tmp_path)
    session, fake = native_writer(case, monkeypatch)
    case.value.work.fence += 1
    try:
        with pytest.raises(ValueError, match="snapshot changed"):
            await restore_wait_locked(
                case.check.services.execution,
                session,
                case.value.control,
                case.value.work,
                case.check,
            )
        fake.scalars.assert_not_awaited()
        fake.flush.assert_not_awaited()
    finally:
        case.check.operation.finish()


async def test_expiry_during_flush_stops_before_more_recovery_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.builder.contained_query import clock_us

    case = await recovery_case(tmp_path)
    session, fake = native_writer(case, monkeypatch)

    async def expire() -> None:
        case.check.operation.end = clock_us() - 1

    fake.flush.side_effect = expire
    try:
        with pytest.raises(TimeoutError):
            await restore_wait_locked(
                case.check.services.execution,
                session,
                case.value.control,
                case.value.work,
                case.check,
            )
        assert fake.scalars.await_count == 1
        assert fake.scalar.await_count == 4
    finally:
        # This supplied transport cannot prove database rollback; the real wrapper
        # owns the transaction and actual recovery persistence is a separate gate.
        case.check.operation.finish()
