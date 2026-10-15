"""Native issuance row delivery only; these shapes do not manufacture accepted E evidence."""

from datetime import timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.issued_facts import require_cycle_publication_intent_locked
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.unit.selected_intent_boundary_fixture import IntentBoundary
from nexus.tests.unit.test_cycle_publication_intent import cycle_boundary


@pytest.mark.parametrize("count", [0, 2])
async def test_all_issued_candidates_are_counted_before_selecting_a_good_state(count: int) -> None:
    case = cycle_boundary()
    session = MagicMock(spec=AsyncSession)
    rows = MagicMock()
    rows.all.return_value = [case.proposal.action_id] * count
    session.scalars = AsyncMock(return_value=rows)
    with pytest.raises(ValueError):
        await require_cycle_publication_intent_locked(
            session, case.work, case.proposal, case.action
        )
    session.get.assert_not_awaited()
    sql = str(session.scalars.await_args.args[0])
    assert "state" not in sql and "succeeded" not in sql


@pytest.mark.parametrize(
    "damage", [None, "hold", "counter", "fence", "attempt", "consumed", "hash"]
)
@pytest.mark.parametrize("index", [4, 5, 6, 7])
async def test_original_issued_attempt_and_positive_hold_are_exact(
    damage: str | None, index: int
) -> None:
    # This >50-line supplied issuance case varies one actual binding and conserves all writes.
    case = cycle_boundary(index)
    effect = case.known()
    effect.created_at = case.now
    attempt = ExecutionAttempt(
        company_id=case.work.company_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        attempt_id=case.proposal.action_id,
        kind="tool_attempts",
        fence=1,
        reserved_at=case.now - timedelta(milliseconds=500),
    )
    if damage == "hold":
        case.hold.amount_usd = Decimal(0)
    elif damage == "counter":
        case.work.tool_attempts_used = True
    elif damage == "fence":
        effect.intent_fence = case.work.fence + 1
    elif damage == "attempt":
        attempt.kind = "model_requests"
    elif damage == "consumed":
        case.action.consumed_at = None
    elif damage == "hash":
        case.action.proposal_hash = "0" * 64
    session = MagicMock(spec=AsyncSession)
    rows = MagicMock()
    rows.all.return_value = [case.proposal.action_id]
    session.scalars = AsyncMock(return_value=rows)

    async def get(model: type[object], key: object) -> object:
        rows: dict[type[object], object] = {
            EffectIntent: effect,
            ExecutionAttempt: attempt,
            CostHold: case.hold,
        }
        return rows[model]

    session.get, session.scalar = AsyncMock(side_effect=get), AsyncMock(return_value=case.now)
    if damage is None:
        observed = await require_cycle_publication_intent_locked(
            session, case.work, case.proposal, case.action
        )
        assert (
            observed.effect is effect and observed.attempt is attempt and observed.hold is case.hold
        )
    else:
        with pytest.raises(ValueError):
            await require_cycle_publication_intent_locked(
                session, case.work, case.proposal, case.action
            )
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def mixed_issuance(index: int = 4) -> tuple[MagicMock, object, list[object]]:
    """Supplied native model+tool journal/attempt/receipt shapes; no provider or accepted E."""
    # Keep one >50-line coherent two-budget fixture so each negative changes exactly one binding.
    from nexus.company.contracts.knowledge import ArtifactRef
    from nexus.harness.model_authorizer_contracts import model_action_parameters
    from nexus.tests.unit.test_company_model_authorizer import recipe
    from nexus.tests.unit.test_company_provider_conformance import request

    case = cycle_boundary(index)
    publication = case.known()
    publication.created_at, publication.intent_fence = case.now, case.work.fence
    publication.state, case.hold.state = "intent", "held"
    attempt = ExecutionAttempt(
        company_id=case.work.company_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        attempt_id=case.proposal.action_id,
        kind="tool_attempts",
        fence=case.work.fence,
        reserved_at=case.now - timedelta(milliseconds=500),
    )
    model_id, request_id = UUID(int=1201), UUID(int=1202)
    call = request().model_copy(
        update={
            "company_id": case.work.company_id,
            "task_id": case.work.task_id,
            "trace_id": case.work.trace_id,
            "actor_id": case.work.actor_id,
            "action_id": model_id,
            "attempt_id": model_id,
            "request_id": request_id,
            "registry_revision": case.work.model_registry_version,
            "price_version": "p1",
        }
    )
    params = model_action_parameters(call, recipe().model_copy(update={"profile": "routine"}))
    model = ActionProposal(
        company_id=case.work.company_id,
        action_id=model_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        actor_id=case.work.actor_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=params,
        estimated_cost_usd=Decimal("0.01"),
        policy_version="p1",
        price_version="p1",
    )
    approval = ApprovalDecision(
        company_id=case.work.company_id,
        decision_id=UUID(int=1203),
        action_id=model_id,
        action_revision=1,
        action_hash=action_hash(model),
        approver_id=case.control.owner_id,
        decision="approved",
        issued_at=case.now - timedelta(seconds=10),
        expires_at=case.now + timedelta(seconds=10),
    )
    journal = JournalAction(
        id=model_id,
        company_id=case.work.company_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        proposal_json=model.model_dump_json(),
        proposal_hash=action_hash(model),
        approval_json=approval.model_dump_json(),
        state="authorized",
        consumed_at=case.now - timedelta(seconds=5),
    )
    receipt = ActionReceipt(
        company_id=case.work.company_id,
        receipt_id=uuid5(model_id, "model-receipt-v1"),
        action_id=model_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        proposal_hash=action_hash(model),
        outcome="succeeded",
        recorded_at=case.now - timedelta(seconds=2),
        artifacts=(
            ArtifactRef(
                company_id=case.work.company_id,
                artifact_id=uuid5(model_id, str(request_id)),
                revision="model-result-envelope-v1",
                sha256="1" * 64,
                reference="supplied-model-evidence-only",
            ),
        ),
    )
    effect = EffectIntent(
        company_id=case.work.company_id,
        action_id=model_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        run_id=case.work.run_id,
        proposal_hash=action_hash(model),
        intent_fence=1,
        attempt_kind="model_requests",
        state="succeeded",
        created_at=case.now - timedelta(seconds=3),
        receipt_json=receipt.model_dump_json(),
    )
    model_attempt = ExecutionAttempt(
        company_id=case.work.company_id,
        task_id=case.work.task_id,
        trace_id=case.work.trace_id,
        attempt_id=model_id,
        kind="model_requests",
        fence=1,
        reserved_at=case.now - timedelta(seconds=4),
    )
    hold = CostHold(
        action_id=model_id,
        company_id=case.work.company_id,
        task_id=case.work.task_id,
        day=case.now.date(),
        amount_usd=model.estimated_cost_usd,
        actual_usd=Decimal("0.001"),
        state="reconciled",
    )
    case.work.model_requests_used = 1
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    result.all.return_value = [model_id, case.proposal.action_id]
    session.scalars = AsyncMock(return_value=result)

    async def get(kind: type[object], key: object) -> object | None:
        if kind is JournalAction:
            return journal if key == model_id else case.action
        selected = key[-1] if isinstance(key, tuple) else key
        records: dict[type[object], object] = (
            {EffectIntent: effect, ExecutionAttempt: model_attempt, CostHold: hold}
            if selected == model_id
            else {EffectIntent: publication, ExecutionAttempt: attempt, CostHold: case.hold}
        )
        return records.get(kind)

    session.get, session.scalar = AsyncMock(side_effect=get), AsyncMock(return_value=case.now)
    return session, case, [journal, effect, model_attempt, hold, publication, attempt]


@pytest.mark.parametrize("index", [4, 6])
async def test_real_native_helper_accepts_one_succeeded_model_plus_one_publication(
    index: int,
) -> None:
    session, supplied, rows = mixed_issuance(index)
    case = cast(IntentBoundary, supplied)
    result = await require_cycle_publication_intent_locked(
        session, case.work, case.proposal, case.action
    )
    assert result.effect is rows[4]
    sql = str(session.scalars.await_args.args[0])
    assert "attempt_kind" not in sql and "state" not in sql
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def rebind_model(rows: list[object], damage: str) -> None:
    """Keep hashes consistent so each negative reaches the intended native binding."""
    record, effect = cast(JournalAction, rows[0]), cast(EffectIntent, rows[1])
    action = ActionProposal.model_validate_json(record.proposal_json)
    parameters = dict(action.parameters)
    changes: dict[str, object] = {}
    if damage in {"misclassified_tool", "failed_tool", "unknown_tool"}:
        changes["tool"] = "company.cycle-artifact.write.v1"
    elif damage == "actor":
        changes["actor_id"] = UUID(int=1300)
    else:
        field = {"pins": "extra", "attempt_id": "attempt_id", "registry": "registry_revision"}
        parameters[field.get(damage, "price_version")] = (
            str(UUID(int=1300)) if damage == "attempt_id" else "other"
        )
        changes["parameters"] = parameters
    action = action.model_copy(update=changes)
    record.proposal_json, record.proposal_hash = action.model_dump_json(), action_hash(action)
    effect.proposal_hash = action_hash(action)
    approval = ApprovalDecision.model_validate_json(record.approval_json or "")
    record.approval_json = approval.model_copy(
        update={"action_hash": action_hash(action)}
    ).model_dump_json()
    receipt = ActionReceipt.model_validate_json(effect.receipt_json or "")
    effect.receipt_json = receipt.model_copy(
        update={"proposal_hash": action_hash(action)}
    ).model_dump_json()


@pytest.mark.parametrize(
    "damage",
    [
        "misclassified_tool",
        "failed_tool",
        "unknown_tool",
        "extra",
        "missing",
        "model_unknown",
        "model_failed",
        "model_intent",
        "pins",
        "attempt_id",
        "registry",
        "price",
        "actor",
        "fence",
        "attempt_kind",
        "hold",
        "receipt_id",
        "late",
        "counter",
        "counter_bool",
        "counter_float",
        "counter_string",
        "delegated",
        "PV",
        "CV",
    ],
)
async def test_only_complete_succeeded_native_model_is_excluded_and_rows_conserved(
    damage: str,
) -> None:
    # Supplied ledger delivery exercises the real helper, not SQL or provider execution.
    from copy import deepcopy

    session, supplied, rows = mixed_issuance({"PV": 5, "CV": 7}.get(damage, 4))
    case = cast(IntentBoundary, supplied)
    effect, attempt, hold = (
        cast(EffectIntent, rows[1]),
        cast(ExecutionAttempt, rows[2]),
        cast(CostHold, rows[3]),
    )
    if damage in {
        "misclassified_tool",
        "failed_tool",
        "unknown_tool",
        "pins",
        "attempt_id",
        "registry",
        "price",
        "actor",
    }:
        rebind_model(rows, damage)
    if damage in {"failed_tool", "unknown_tool"}:
        effect.attempt_kind = attempt.kind = "tool_attempts"
        effect.state = "failed" if damage == "failed_tool" else "outcome_unknown"
    elif damage == "extra":
        session.scalars.return_value.all.return_value.append(UUID(int=1300))
    elif damage == "missing":
        session.scalars.return_value.all.return_value = [case.proposal.action_id]
    elif damage.startswith("model_"):
        effect.state = {
            "model_unknown": "outcome_unknown",
            "model_failed": "failed",
            "model_intent": "intent",
        }[damage]
    elif damage == "fence":
        effect.intent_fence = attempt.fence = case.work.fence + 1
    elif damage == "attempt_kind":
        attempt.kind = "tool_attempts"
    elif damage == "hold":
        hold.state, hold.actual_usd = "outcome_unknown", None
    elif damage in {"receipt_id", "late"}:
        receipt = ActionReceipt.model_validate_json(effect.receipt_json or "")
        field, value = (
            ("receipt_id", UUID(int=1300))
            if damage == "receipt_id"
            else ("recorded_at", case.now + timedelta(seconds=1))
        )
        effect.receipt_json = receipt.model_copy(update={field: value}).model_dump_json()
    elif damage.startswith("counter"):
        counters: dict[str, object] = {
            "counter": 0,
            "counter_bool": True,
            "counter_float": 1.0,
            "counter_string": "1",
        }
        case.work.model_requests_used = counters[damage]  # type: ignore[assignment]
    elif damage == "delegated":
        case.work.model_requests_delegated = 1
    selected = [case.work, case.action, case.hold, *rows]
    before = deepcopy(
        [
            {key: value for key, value in vars(row).items() if not key.startswith("_sa_")}
            for row in selected
        ]
    )
    with pytest.raises(ValueError):
        await require_cycle_publication_intent_locked(
            session, case.work, case.proposal, case.action
        )
    assert [
        {key: value for key, value in vars(row).items() if not key.startswith("_sa_")}
        for row in selected
    ] == before
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
