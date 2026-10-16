"""Actual EffectStore.begin mandatory-hook boundary with explicitly supplied SQL authority.

Qualification goal validation has its own tests; only that awaited delivery is
mocked here, while concrete type/composition checks and native mutation order run.
"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.core.llm.qualification_contracts import PROFILE, TOOL, WORKFLOW
from nexus.execution.effect_store import EffectStore
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionRegistration
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CostHold
from nexus.harness.qualification_intent import QualificationIntentCheck
from nexus.tests.unit.selected_intent_boundary_fixture import (
    IntentBoundary,
    NoOpIntentCheck,
    intent_boundary,
)
from nexus.tests.unit.test_qualification_intent import native


async def boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[IntentBoundary, EffectStore, QualificationIntentCheck]:
    original, session, control, work, action, _ = native()
    hold = await session.get(CostHold, action.id)
    assert hold is not None
    assert action.consumed_at is not None
    base = intent_boundary()
    case = IntentBoundary(
        base.catalog.model_copy(update={"cycle_admission": None}),
        work,
        original._lease,
        original._identity,
        ActionProposal.model_validate_json(action.proposal_json),
        action,
        hold,
        control,
        action.consumed_at,
    )
    store = case.install(monkeypatch)
    check = QualificationIntentCheck(
        store._factory, store, case.lease, case.identity, original._recipe, original._request
    )
    return case, store, check


def untouched(case: IntentBoundary, *, issued: bool = False) -> None:
    assert case.added == []
    assert all(
        getattr(case.work, f"{kind}_used") == int(issued and kind == "model_requests")
        for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions")
    )
    assert case.hold.actual_usd is None and case.hold.state == ("unknown" if issued else "held")
    assert case.hold.amount_usd == case.proposal.estimated_cost_usd
    assert case.hold.day == billing_day(case.now)
    assert all(
        getattr(case.work, f"{kind}_delegated") == 0
        for kind in ("model_requests", "tool_attempts", "rework_rounds", "plan_revisions")
    )
    case.hold_move.assert_not_awaited()
    case.session.flush.assert_not_awaited()


def markers(case: IntentBoundary, workflow: str, profile: str, tool: str) -> None:
    registration = ExecutionRegistration.model_validate_json(
        case.work.registration_json
    ).model_copy(update={"workflow_name": workflow, "model_profile": profile})
    case.work.workflow_name, case.work.model_profile = workflow, profile
    case.work.registration_json = registration.model_dump_json()
    case.work.registration_hash = registration_digest(registration)
    proposal = case.proposal.model_copy(update={"tool": tool})
    case.action.proposal_json, case.action.proposal_hash = (
        proposal.model_dump_json(),
        action_hash(proposal),
    )


@pytest.mark.parametrize("which", ["missing", "noop", "composite"])
async def test_missing_or_protocol_only_qualification_hook_denies_before_mutation(
    monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    case, store, _ = await boundary(monkeypatch)
    noop = NoOpIntentCheck()
    supplied: BeforeIntentCheck | None = None if which == "missing" else noop
    if which == "composite":
        supplied = CompositeBeforeIntentCheck((noop,))
    with pytest.raises(ExecutionDeniedError, match="qualification"):
        await store.begin(
            case.lease, case.identity, case.action.id, kind="model_requests", before_intent=supplied
        )
    untouched(case)
    assert noop.calls == 0


@pytest.mark.parametrize("marker", ["workflow", "profile", "tool"])
async def test_any_reserved_qualification_marker_requires_closed_check(
    monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    case, store, _ = await boundary(monkeypatch)
    markers(
        case,
        WORKFLOW if marker == "workflow" else "ordinary",
        PROFILE if marker == "profile" else "routine",
        TOOL if marker == "tool" else "ordinary.tool",
    )
    with pytest.raises(ExecutionDeniedError, match="qualification"):
        await store.begin(case.lease, case.identity, case.action.id, kind="model_requests")
    untouched(case)


async def test_wrong_attempt_kind_denies_before_hook_or_hold_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, store, check = await boundary(monkeypatch)
    validate = AsyncMock()
    monkeypatch.setattr(QualificationIntentCheck, "validate", validate)
    with pytest.raises(ExecutionDeniedError, match="qualification"):
        await store.begin(
            case.lease, case.identity, case.action.id, kind="tool_attempts", before_intent=check
        )
    untouched(case)
    validate.assert_not_awaited()


async def test_known_issued_replay_keeps_original_record_without_new_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, store, _ = await boundary(monkeypatch)
    case.previous = EffectIntent(
        company_id=case.work.company_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        run_id=case.work.run_id,
        action_id=case.action.id,
        proposal_hash=case.action.proposal_hash,
        intent_fence=case.work.fence,
        attempt_kind="model_requests",
        state="outcome_unknown",
        created_at=case.now,
        receipt_json=None,
        verification_json=None,
    )
    case.work.model_requests_used = 1
    case.hold.state = "unknown"
    result = await store.begin(case.lease, case.identity, case.action.id, kind="model_requests")
    assert not result.permit_external_call and result.record.state == "outcome_unknown"
    untouched(case, issued=True)
    case.authority.assert_not_awaited()


async def test_normal_nonqualification_begin_keeps_existing_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = intent_boundary()
    case.catalog = case.catalog.model_copy(update={"cycle_admission": None})
    result = await case.install(monkeypatch).begin(case.lease, case.identity, case.action.id)
    assert result.permit_external_call and case.work.tool_attempts_used == 1


@pytest.mark.parametrize("phase", ["validate", "final-flush"])
@pytest.mark.parametrize("drift", ["markers", "effects"])
async def test_qualification_markers_cannot_switch_to_generic_after_await(
    monkeypatch: pytest.MonkeyPatch, phase: str, drift: str
) -> None:
    case, store, check = await boundary(monkeypatch)

    async def mutate(*args: object) -> None:
        if drift == "markers":
            markers(case, "ordinary", "routine", "ordinary.tool")
        else:
            check._effects = EffectStore(store._factory)

    monkeypatch.setattr(
        QualificationIntentCheck, "validate", mutate if phase == "validate" else AsyncMock()
    )
    monkeypatch.setattr(QualificationIntentCheck, "validate_time", lambda *_: None)
    if phase == "final-flush":
        case.session.flush.side_effect = mutate
    with pytest.raises(ExecutionDeniedError, match="qualification"):
        await store.begin(
            case.lease, case.identity, case.action.id, kind="model_requests", before_intent=check
        )
    if phase == "validate":
        untouched(case)


async def test_generic_classification_cannot_become_qualification_after_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = intent_boundary()
    case.catalog = case.catalog.model_copy(update={"cycle_admission": None})
    store = case.install(monkeypatch)
    check = NoOpIntentCheck()

    async def mutate(*args: object, **kwargs: object) -> None:
        markers(case, WORKFLOW, PROFILE, TOOL)

    monkeypatch.setattr(check, "validate", mutate)
    with pytest.raises(ExecutionDeniedError, match="qualification"):
        await store.begin(case.lease, case.identity, case.action.id, before_intent=check)
    untouched(case)


@pytest.mark.parametrize("splice", ["factory", "lease", "identity", "subclass"])
async def test_foreign_concrete_hook_denies_before_native_mutation(
    monkeypatch: pytest.MonkeyPatch, splice: str
) -> None:
    case, store, check = await boundary(monkeypatch)
    if splice == "factory":
        check._factory = object()  # type: ignore[assignment]
    elif splice == "lease":
        check._lease = check._lease.model_copy(update={"fence": check._lease.fence + 1})
    elif splice == "identity":
        check._identity = check._identity.model_copy(update={"principal_id": UUID(int=999)})
    else:

        class Substitute(QualificationIntentCheck):
            pass

        check.__class__ = Substitute
    validate = AsyncMock()
    monkeypatch.setattr(QualificationIntentCheck, "validate", validate)
    monkeypatch.setattr(QualificationIntentCheck, "validate_time", lambda *_: None)
    with pytest.raises(ExecutionDeniedError, match="qualification"):
        await store.begin(
            case.lease, case.identity, case.action.id, kind="model_requests", before_intent=check
        )
    untouched(case)
    validate.assert_not_awaited()


async def test_exact_original_qualification_check_reaches_one_native_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, store, check = await boundary(monkeypatch)
    validate = AsyncMock()
    monkeypatch.setattr(QualificationIntentCheck, "validate", validate)
    monkeypatch.setattr(QualificationIntentCheck, "validate_time", lambda *_: None)
    result = await store.begin(
        case.lease, case.identity, case.action.id, kind="model_requests", before_intent=check
    )
    assert result.permit_external_call and result.record.attempt_kind == "model_requests"
    assert case.work.model_requests_used == 1 and len(case.added) == 2
    validate.assert_awaited_once()
