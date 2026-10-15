"""Concrete trusted composition and scoped choice declarations precede any transition write."""

from unittest.mock import MagicMock

import pytest

from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.strategy_transition import (
    is_full_transition,
    require_transition_dependencies,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.tests.unit.cycle_admission_fixture import declared
from nexus.tests.unit.cycle_full_structural_support import configured
from nexus.tests.unit.plan_admission_witness_fixture import bound_witness
from nexus.tests.unit.test_plan_choice_wire_integration import selection


@pytest.mark.parametrize("stage", [1, 2])
def test_strategy_stage_choice_and_full_missing_choice_deny(stage: int) -> None:
    data = configured()
    payload = declared(data.admission, stage)
    if stage == 1:
        payload = payload.model_copy(update={"strategy_selection": selection()})
    with pytest.raises(ManagementDeniedError):
        is_full_transition(payload, data.catalog)


@pytest.mark.parametrize("part", ["freshness", "reader", "credential", "identity", "catalog"])
async def test_unconfigured_process_values_cannot_supply_a_current_proof(part: str) -> None:
    from nexus.tests.unit.strategy_current_proof_fixture import proof_case

    with pytest.MonkeyPatch.context() as monkeypatch:
        case = proof_case(monkeypatch)
        data = configured()
        payload = declared(data.admission, 2).model_copy(update={"strategy_selection": selection()})
        case.reader.catalog = data.catalog
        credential = await bound_witness(data.admission.procedure.binding)
        freshness = case.reader.freshness if part != "freshness" else MagicMock()
        reader = case.service if part != "reader" else object()
        witness = credential if part != "credential" else object()
        identity = credential.identity if part != "identity" else case.credential.identity
        require_transition_dependencies(
            payload,
            data.catalog,
            case.reader.freshness,
            case.service,
            credential,
            credential.identity,
        )
        if part == "catalog":
            case.reader.catalog = case.reader.catalog.model_copy(
                update={"check_recipes": frozenset({"changed.recipe.v1"})}
            )
        with pytest.raises(ManagementDeniedError):
            require_transition_dependencies(
                payload, data.catalog, freshness, reader, witness, identity
            )


def test_constructor_rejects_a_reader_or_freshness_from_another_factory() -> None:
    from nexus.tests.unit.strategy_current_proof_fixture import proof_case

    with pytest.MonkeyPatch.context() as monkeypatch:
        case = proof_case(monkeypatch)
        with pytest.raises(ManagementDeniedError):
            ManagementPlanStore(
                MagicMock(),
                case.reader.catalog,
                source_freshness=case.reader.freshness,
                strategy_proof_reader=case.service,
            )
