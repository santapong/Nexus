"""Supplied transition data consistency only; no owner proof, SQL or admission authority."""

from datetime import timedelta

import pytest

from nexus.company.management.strategy_transition_observation import validate_transition_proof
from nexus.company.management.transactions import ManagementDeniedError
from nexus.tests.unit.strategy_transition_observation_fixture import transition_case


def test_exact_descriptive_change_matches_full_layout() -> None:
    case = transition_case()
    assert (
        validate_transition_proof(case.payload, case.catalog, case.proof)
        == case.observation.candidate
    )


@pytest.mark.parametrize(
    "change",
    [
        "selection",
        "goal",
        "root",
        "plan",
        "sv",
        "policy",
        "brief",
        "acceptance",
        "registration",
        "defer",
    ],
)
def test_spliced_transition_description_denies(change: str) -> None:
    case = transition_case()
    case.splice(change)
    with pytest.raises((ManagementDeniedError, ValueError)):
        validate_transition_proof(case.payload, case.catalog, case.proof)


def test_fingerprint_preserves_original_proof_across_current_head_and_clock() -> None:
    case = transition_case()
    current = case.at_head_two()
    case.observation.require_same_proof(current)
    assert case.proof.current.pair.plan.plan.revision == 1
    assert current.proof.current.pair.plan.plan.revision == 2


@pytest.mark.parametrize(
    "field",
    [
        "selection",
        "original",
        "acceptance",
        "brief",
        "verifier",
        "check_result",
        "author_original_fence",
        "author_current_fence",
        "verifier_current_fence",
    ],
)
def test_every_immutable_fingerprint_component_is_retained(field: str) -> None:
    case = transition_case()
    current = case.changed_fingerprint(field)
    with pytest.raises((ManagementDeniedError, ValueError)):
        case.observation.require_same_proof(current)


@pytest.mark.parametrize("which", ["plan", "proof"])
def test_final_clock_keeps_both_independent_windows(which: str) -> None:
    case = transition_case()
    observation = case.expiring(which)
    observation.require_time(case.now)
    with pytest.raises(ValueError):
        observation.require_time(case.now + timedelta(seconds=10))
