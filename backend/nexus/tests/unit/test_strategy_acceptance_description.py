"""Descriptive proof construction is independent of native acceptance authority."""

import json
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy.acceptance import build_strategy_acceptance
from nexus.company.strategy.artifact_contracts import StrategyCheckParameters
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.verifier_receipt import StrategyVerifierReceipt
from nexus.harness.canonical import action_hash
from nexus.tests.unit.strategy_brief_fixture import strategy_case
from nexus.tests.unit.strategy_verifier_receipt_fixture import ReceiptCase, receipt_case
from nexus.tests.unit.test_strategy_check_output import inputs


def _actual_description(case: ReceiptCase) -> tuple[StrategyVerifierReceipt, bytes]:
    command, manifest = strategy_case().command, inputs()
    prepared = prepare_strategy_check(command, manifest, "internal")
    pins = case.action.parameters | {
        "output_sha256": prepared.output_sha256,
        "input_snapshot_sha256": prepared.input_snapshot_sha256,
    }
    action = case.action.model_copy(update={"parameters": pins})
    reference = case.reference.model_copy(
        update={"sha256": prepared.output_sha256, "byte_length": len(prepared.raw_bytes)}
    )
    receipt = case.receipt.model_copy(
        update={
            "proposal_hash": action_hash(action),
            "artifacts": (
                ArtifactRef(
                    company_id=reference.company_id,
                    artifact_id=reference.artifact_id,
                    reference="protected synthetic result",
                    revision=reference.revision,
                    sha256=reference.sha256,
                ),
            ),
        }
    )
    return (
        StrategyVerifierReceipt(
            action,
            receipt,
            1,
            reference,
            StrategyCheckParameters.model_validate_json(json.dumps(pins)),
        ),
        prepared.raw_bytes,
    )


def test_exact_recomputed_description_retains_mechanical_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    verifier, raw = _actual_description(case)
    now = case.clock["now"]
    result = build_strategy_acceptance(strategy_case().command, inputs(), verifier, raw, now)
    assert result.verdict == "pass" and result.target == case.target
    assert "mechanical_strategy_brief_only" in result.limitations
    assert "business_readiness_unproven" in result.limitations
    assert len(result.proofs) == 1
    replay = build_strategy_acceptance(
        strategy_case().command, inputs(), verifier, raw, now + timedelta(seconds=1)
    )
    assert replay.acceptance_id == result.acceptance_id and replay.proofs == result.proofs


@pytest.mark.parametrize(
    "kind", ["input_hash", "output_hash", "target", "actor", "receipt", "time"]
)
def test_crossed_original_receipt_or_production_pins_deny(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    case = receipt_case(monkeypatch)
    verifier, raw = _actual_description(case)
    now = case.clock["now"]
    if kind in {"input_hash", "output_hash", "target"}:
        key = {
            "input_hash": "input_snapshot_sha256",
            "output_hash": "output_sha256",
            "target": "verification_target_sha256",
        }[kind]
        verifier = replace(
            verifier, parameters=verifier.parameters.model_copy(update={key: "b" * 64})
        )
    elif kind == "actor":
        verifier = replace(
            verifier, action=verifier.action.model_copy(update={"actor_id": UUID(int=999)})
        )
    elif kind == "receipt":
        verifier = replace(
            verifier, receipt=verifier.receipt.model_copy(update={"outcome": "outcome_unknown"})
        )
    else:
        now -= timedelta(seconds=1)
    with pytest.raises(AcceptanceDeniedError):
        build_strategy_acceptance(strategy_case().command, inputs(), verifier, raw, now)


def test_supplied_pass_bytes_cannot_replace_recomputed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    verifier, raw = _actual_description(case)
    raw = raw.replace(b'"verdict":"pass"', b'"verdict":"reject"', 1)
    with pytest.raises(AcceptanceDeniedError):
        build_strategy_acceptance(
            strategy_case().command, inputs(), verifier, raw, case.clock["now"]
        )
