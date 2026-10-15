"""Actual EffectStore.begin control flow with explicit supplied authority/session boundaries."""

import pytest

from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.unit.selected_intent_boundary_fixture import (
    NoOpIntentCheck,
    intent_boundary,
    sender_intent_boundary,
)
from nexus.tests.unit.selected_intent_boundary_guard import defective_check


@pytest.mark.parametrize("verifier", [False, True])
@pytest.mark.parametrize("which", ["missing", "noop", "composite_noop"])
async def test_fresh_mixed_intent_requires_real_selected_guard_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch, verifier: bool, which: str
) -> None:
    case = intent_boundary(verifier)
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    check: BeforeIntentCheck | None = None if which == "missing" else noop
    if which == "composite_noop":
        check = CompositeBeforeIntentCheck((noop,))
    with pytest.raises(ExecutionDeniedError, match=r"selected|Selected"):
        await store.begin(case.lease, case.identity, case.proposal.action_id, before_intent=check)
    case.untouched()
    assert noop.calls == 0


@pytest.mark.parametrize("verifier", [False, True])
async def test_previous_intent_returns_original_unknown_without_selected_read_or_attempt(
    monkeypatch: pytest.MonkeyPatch, verifier: bool
) -> None:
    case = intent_boundary(verifier)
    original = case.known()
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    result = await store.begin(
        case.lease, case.identity, case.proposal.action_id, before_intent=noop
    )
    assert result.permit_external_call is False
    assert result.record.state == "outcome_unknown"
    assert result.record.intent_fence == original.intent_fence == 1
    assert result.record.receipt is None and case.work.fence == 2
    case.untouched(issued=True)
    case.authority.assert_not_awaited()
    case.management.assert_not_awaited()
    assert noop.calls == 0


async def test_absent_cycle_configuration_preserves_original_direct_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = intent_boundary()
    case.catalog = case.catalog.model_copy(update={"cycle_admission": None})
    store = case.install(monkeypatch)
    result = await store.begin(case.lease, case.identity, case.proposal.action_id)
    assert result.permit_external_call is True
    assert result.record.intent_fence == case.lease.fence
    assert case.work.tool_attempts_used == 1
    assert len(case.added) == 2
    case.hold_move.assert_awaited_once()


@pytest.mark.parametrize("field", ["fence", "worker_id", "segment_id"])
async def test_native_stale_lease_denies_before_selected_check_or_mutation(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    from uuid import UUID

    case = intent_boundary()
    lease = case.lease.model_copy(update={field: 99 if field == "fence" else UUID(int=999)})
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    with pytest.raises(ExecutionDeniedError, match="lease"):
        await store.begin(lease, case.identity, case.proposal.action_id, before_intent=noop)
    case.untouched()
    case.authority.assert_not_awaited()
    assert noop.calls == 0


@pytest.mark.parametrize("verifier", [False, True])
@pytest.mark.parametrize(
    "defect",
    [
        "plain",
        "missing_parent",
        "noop_guard",
        "guard_subclass",
        "parent_subclass",
        "composite_subclass",
        "extra",
        "reversed",
        "lease",
        "action",
        "parent_scope",
        "parent_service",
    ],
)
async def test_malformed_concrete_check_cannot_reach_selected_read_or_native_mutation(
    monkeypatch: pytest.MonkeyPatch, verifier: bool, defect: str
) -> None:
    case = intent_boundary(verifier)
    check, store = defective_check(case, defect), case.install(monkeypatch)
    with pytest.raises(ExecutionDeniedError, match=r"selected|Selected"):
        await store.begin(case.lease, case.identity, case.proposal.action_id, before_intent=check)
    case.untouched()
    case.management.assert_not_awaited()


@pytest.mark.parametrize("which", ["missing", "noop", "composite_noop"])
async def test_fresh_mixed_sender_requires_native_check_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = sender_intent_boundary()
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    check: BeforeIntentCheck | None = None if which == "missing" else noop
    if which == "composite_noop":
        check = CompositeBeforeIntentCheck((noop,))
    with pytest.raises(
        ExecutionDeniedError,
        match=r"^Fresh mixed sender intent requires its exact native checks$",
    ):
        await store.begin(case.lease, case.identity, case.proposal.action_id, before_intent=check)
    case.untouched()
    case.authority.assert_awaited_once()
    case.management.assert_not_awaited()
    assert noop.calls == 0


@pytest.mark.parametrize("which", ["missing", "noop", "composite_noop"])
async def test_previous_mixed_sender_unknown_returns_without_fresh_check_or_attempt(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case = sender_intent_boundary()
    original = case.known()
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    check: BeforeIntentCheck | None = None if which == "missing" else noop
    if which == "composite_noop":
        check = CompositeBeforeIntentCheck((noop,))
    result = await store.begin(
        case.lease, case.identity, case.proposal.action_id, before_intent=check
    )
    assert result.permit_external_call is False
    assert result.record.state == original.state == "outcome_unknown"
    assert result.record.intent_fence == original.intent_fence == 1
    assert result.record.created_at == original.created_at
    assert result.record.proposal_hash == original.proposal_hash
    assert result.record.receipt is None and result.record.verification is None
    assert case.previous is original and original.receipt_json is None
    assert original.verification_json is None and case.work.fence == 2
    case.untouched(issued=True)
    case.authority.assert_not_awaited()
    case.management.assert_not_awaited()
    assert noop.calls == 0


@pytest.mark.parametrize("field", ["fence", "worker_id", "segment_id", "expired"])
async def test_stale_mixed_sender_lease_denies_before_fresh_check_or_mutation(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    from uuid import UUID

    case = sender_intent_boundary()
    lease = case.lease
    if field == "expired":
        case.work.lease_until = case.now
    else:
        lease = lease.model_copy(update={field: 99 if field == "fence" else UUID(int=999)})
    store, noop = case.install(monkeypatch), NoOpIntentCheck()
    with pytest.raises(
        ExecutionDeniedError, match=r"^Execution lease is stale, expired or differently bound$"
    ):
        await store.begin(lease, case.identity, case.proposal.action_id, before_intent=noop)
    case.untouched()
    case.authority.assert_not_awaited()
    case.management.assert_not_awaited()
    assert noop.calls == 0
