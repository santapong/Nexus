"""Receipt-ledger binding and final clocks; actual plan/source/SQL qualification is separate."""

from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.notifications.worker_identity import WorkerIdentityDeniedError
from nexus.company.strategy.verifier_receipt import (
    StrategyVerifierReceipt,
    require_strategy_verifier_receipt,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.harness.canonical import action_hash
from nexus.tests.unit.strategy_verifier_receipt_fixture import ReceiptCase, receipt_case


async def _read(case: ReceiptCase) -> StrategyVerifierReceipt:
    return await require_strategy_verifier_receipt(
        case.session,
        case.control,
        case.lease,
        case.credential.identity,
        case.target,
        verifier_action_id=case.action.action_id,
        protected_result=case.reference,
        rule=case.rule,
        credential=case.credential,
        artifacts=case.artifacts,
    )


async def test_original_succeeded_receipt_keeps_its_fence_without_claiming_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    result = await _read(case)
    assert result.original_intent_fence == 1 and case.lease.fence == 3
    assert result.receipt == case.receipt and result.protected_result == case.reference
    assert not hasattr(result, "verdict")


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "outcome_unknown"),
        ("state", "intent"),
        ("state", "failed"),
        ("receipt_json", None),
        ("attempt_kind", "model_requests"),
        ("intent_fence", 4),
        ("intent_fence", 0),
        ("run_id", UUID(int=999)),
        ("task_id", UUID(int=999)),
        ("proposal_hash", "b" * 64),
        ("action_id", UUID(int=999)),
        ("company_id", UUID(int=999)),
    ],
)
async def test_unsucceeded_or_crossed_intent_cannot_supply_acceptance_receipt(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = receipt_case(monkeypatch)
    setattr(case.effect, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "pending"),
        ("consumed_at", None),
        ("proposal_hash", "b" * 64),
        ("task_id", UUID(int=999)),
        ("trace_id", UUID(int=999)),
        ("company_id", UUID(int=999)),
    ],
)
async def test_wrong_actual_journal_binding_denies(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = receipt_case(monkeypatch)
    setattr(case.journal, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "model_requests"),
        ("fence", 3),
        ("attempt_id", UUID(int=999)),
        ("trace_id", UUID(int=999)),
    ],
)
async def test_original_attempt_cannot_be_replaced_by_current_fence(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = receipt_case(monkeypatch)
    setattr(case.attempt, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "failed"),
        ("proposal_hash", "b" * 64),
        ("action_id", UUID(int=999)),
        ("task_id", UUID(int=999)),
        ("trace_id", UUID(int=999)),
        ("company_id", UUID(int=999)),
        ("artifacts", ()),
    ],
)
async def test_wrong_or_empty_actual_receipt_denies(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = receipt_case(monkeypatch)
    case.effect.receipt_json = case.receipt.model_copy(update={field: value}).model_dump_json()
    with pytest.raises((AcceptanceDeniedError, ValueError)):
        await _read(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_text", "changed"),
        ("derivation_id", UUID(int=999)),
        ("resource_id", UUID(int=999)),
        ("media_type", "text/plain"),
        ("data_classification", "public"),
        ("artifact_revision_id", UUID(int=999)),
        ("sha256", "b" * 64),
    ],
)
async def test_unrelated_protected_result_denies(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = receipt_case(monkeypatch)
    setattr(case.artifact, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


async def test_forged_target_cannot_relabel_the_original_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    case.target = case.target.model_copy(update={"action_id": UUID(int=999)})
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


async def test_changed_journal_tool_cannot_alias_report_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    action = case.action.model_copy(update={"tool": "company.report.check.v1"})
    case.journal.proposal_json = action.model_dump_json()
    case.journal.proposal_hash = action_hash(action)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


@pytest.mark.parametrize("kind", ["lease", "credential"])
async def test_last_result_lookup_crossing_expiry_denies(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    case = receipt_case(monkeypatch)
    original = case.session.get.side_effect

    async def get(model: object, key: object) -> object:
        value = await original(model, key)
        if value is case.artifact:
            case.clock["now"] = (
                case.lease.expires_at if kind == "lease" else case.credential.expires_at
            )
        return value

    case.session.get.side_effect = get
    with pytest.raises((ExecutionDeniedError, WorkerIdentityDeniedError)):
        await _read(case)


async def test_future_receipt_timestamp_is_not_current_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    case.effect.receipt_json = case.receipt.model_copy(
        update={"recorded_at": case.clock["now"] + timedelta(seconds=1)}
    ).model_dump_json()
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)


@pytest.mark.parametrize("offset", [-1, 1])
async def test_protected_metadata_must_follow_intent_and_precede_receipt(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    case = receipt_case(monkeypatch)
    case.artifact.recorded_at = case.receipt.recorded_at + timedelta(seconds=offset)
    with pytest.raises(AcceptanceDeniedError):
        await _read(case)
