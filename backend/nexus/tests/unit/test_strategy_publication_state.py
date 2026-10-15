"""Known bytes do not turn failed/unknown native issuance into a fresh success."""

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy.publication_state import require_fresh_strategy_publication_state
from nexus.tests.unit.strategy_verifier_receipt_fixture import receipt_case


@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.parametrize("state", ["failed", "outcome_unknown"])
def test_failed_or_unknown_effect_denies_even_when_output_exists(
    monkeypatch: pytest.MonkeyPatch, exists: bool, state: str
) -> None:
    case = receipt_case(monkeypatch)
    case.effect.state = state
    case.effect.receipt_json = None
    with pytest.raises(AcceptanceDeniedError):
        require_fresh_strategy_publication_state(
            case.effect, exists=exists, output=case.reference, action_id=case.action.action_id
        )


@pytest.mark.parametrize("exists", [False, True])
def test_original_pending_intent_can_publish_or_read_its_exact_pending_output(
    monkeypatch: pytest.MonkeyPatch, exists: bool
) -> None:
    case = receipt_case(monkeypatch)
    case.effect.state, case.effect.receipt_json = "intent", None
    require_fresh_strategy_publication_state(
        case.effect, exists=exists, output=case.reference, action_id=case.action.action_id
    )


def test_succeeded_replay_needs_actual_output_and_exact_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = receipt_case(monkeypatch)
    require_fresh_strategy_publication_state(
        case.effect, exists=True, output=case.reference, action_id=case.action.action_id
    )
    with pytest.raises(AcceptanceDeniedError):
        require_fresh_strategy_publication_state(
            case.effect, exists=False, output=case.reference, action_id=case.action.action_id
        )
    changed = case.reference.model_copy(update={"sha256": "b" * 64})
    with pytest.raises(AcceptanceDeniedError):
        require_fresh_strategy_publication_state(
            case.effect, exists=True, output=changed, action_id=case.action.action_id
        )
