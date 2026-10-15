"""Selected guard delegates current gates; mocked delivery is not actual SQL qualification."""

from copy import copy
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.builder.selected_strategy_guard import selected_proof_deadlines
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.management.acceptance_freshness import QualifiedFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy.actor_proof_contracts import SelectedStrategyProof
from nexus.core.llm.company_registry import ModelRegistration
from nexus.execution.intent_checks import CompositeBeforeIntentCheck
from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog
from nexus.tests.unit.selected_strategy_guard_fixture import guard_case


async def test_disclosure_delegates_base_then_same_session_actor_and_keeps_finite_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    values = await case.guard.disclosure_windows(case.session, case.control)
    assert case.order == ["base", "actor"]
    assert case.now + timedelta(seconds=60) in values
    assert case.guard.credential.expires_at in values
    case.guard.deadlines = values
    case.guard.validate_time(case.now)
    with pytest.raises(ValueError):
        case.guard.validate_time(case.now + timedelta(seconds=60))


async def test_first_proof_window_survives_a_later_longer_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    first = case.selected
    short = first.proof.initial.grants[0].model_copy(
        update={"expires_at": case.now + timedelta(seconds=10)}
    )
    first = replace(
        first, proof=replace(first.proof, initial=replace(first.proof.initial, grants=(short,)))
    )
    current = case.selected
    monkeypatch.setattr(
        case.guard.reader, "load_selected_locked", AsyncMock(side_effect=[first, current])
    )
    await case.guard.disclosure_windows(case.session, case.control)
    case.guard.deadlines = await case.guard.disclosure_windows(case.session, case.control)
    with pytest.raises(ValueError):
        case.guard.validate_time(case.now + timedelta(seconds=10))


async def test_current_proof_shorter_window_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    case = guard_case(monkeypatch)
    first = case.selected
    short = first.proof.current.grants[0].model_copy(
        update={"expires_at": case.now + timedelta(seconds=9)}
    )
    current = replace(
        first, proof=replace(first.proof, current=replace(first.proof.current, grants=(short,)))
    )
    monkeypatch.setattr(
        case.guard.reader, "load_selected_locked", AsyncMock(side_effect=[first, current])
    )
    await case.guard.disclosure_windows(case.session, case.control)
    case.guard.deadlines = await case.guard.disclosure_windows(case.session, case.control)
    with pytest.raises(ValueError):
        case.guard.validate_time(case.now + timedelta(seconds=9))


def profiled(
    selected: SelectedStrategyProof, models: tuple[ModelRegistration, ...]
) -> SelectedStrategyProof:
    proof = selected.proof
    catalog = proof.initial.catalog
    registry = catalog.models.model_copy(update={"models": models})
    rebuilt = cycle_catalog(registry).catalog
    assert catalog.cycle_admission is not None
    catalog = catalog.model_copy(
        update={
            "models": registry,
            "native_profiles": rebuilt.native_profiles,
            "notification_profiles": rebuilt.notification_profiles,
            "cycle_admission": catalog.cycle_admission.model_copy(
                update={"registry_sha256": canonical_sha256(registry)}
            ),
        }
    )
    return replace(
        selected,
        proof=replace(
            proof,
            initial=replace(proof.initial, catalog=catalog),
            current=replace(proof.current, catalog=catalog),
        ),
    )


def test_initial_any_model_family_keeps_valid_alternative_and_excludes_future_rescue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    old = case.selected.proof.initial.catalog.models.models[0]

    def model(seconds: int, start: int = -1) -> ModelRegistration:
        return old.model_copy(
            update={
                "registry_id": f"model-{seconds}-{start}",
                "endpoint_id": f"endpoint-{seconds}-{start}",
                "health": old.health.model_copy(
                    update={
                        "checked_at": case.now + timedelta(seconds=start),
                        "expires_at": case.now + timedelta(seconds=seconds),
                    }
                ),
                "evaluations": tuple(
                    e.model_copy(
                        update={
                            "evaluated_at": case.now + timedelta(seconds=start),
                            "expires_at": case.now + timedelta(seconds=seconds),
                        }
                    )
                    for e in old.evaluations
                ),
            }
        )

    selected = profiled(case.selected, (model(10), model(20), model(100, 5)))
    values = selected_proof_deadlines(selected)
    assert case.now + timedelta(seconds=20) in values
    assert case.now + timedelta(seconds=10) not in values
    assert case.now + timedelta(seconds=100) not in values
    selected.require_time(case.now + timedelta(seconds=11))
    selected = profiled(case.selected, (model(100, 5),))
    selected = replace(
        selected, proof=replace(selected.proof, observed_at=case.now + timedelta(seconds=6))
    )
    selected.require_time(case.now + timedelta(seconds=6))
    with pytest.raises(ValueError):
        selected_proof_deadlines(selected)


async def test_selected_pins_or_actor_failure_propagates_without_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    monkeypatch.setattr(
        case.guard.reader,
        "load_selected_locked",
        AsyncMock(side_effect=ValueError("nominated actual reader denial")),
    )
    with pytest.raises(ValueError):
        await case.guard.disclosure_windows(case.session, case.control)
    assert case.order == ["base"]
    with pytest.raises(ValueError):
        case.guard.validate_time(case.now)


async def test_base_denial_precedes_actor_material_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    denied = AsyncMock(side_effect=ValueError("actual base disclosure denied"))
    actor = AsyncMock(return_value=case.selected)
    monkeypatch.setattr(BuilderSourceGuard, "disclosure_windows", denied)
    monkeypatch.setattr(case.guard.reader, "load_selected_locked", actor)
    with pytest.raises(ValueError):
        await case.guard.disclosure_windows(case.session, case.control)
    actor.assert_not_awaited()


async def test_borrowed_owner_witness_in_returned_proof_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.tests.unit.strategy_transition_observation_fixture import transition_case

    case = guard_case(monkeypatch)
    owner = transition_case().proof.initial.sources.credential
    proof = case.selected.proof
    initial = replace(proof.initial, sources=replace(proof.initial.sources, credential=owner))
    selected = replace(case.selected, proof=replace(proof, initial=initial))
    monkeypatch.setattr(case.guard.reader, "load_selected_locked", AsyncMock(return_value=selected))
    with pytest.raises(ValueError):
        await case.guard.disclosure_windows(case.session, case.control)


@pytest.mark.parametrize("available", [True, False])
async def test_qualified_no_ttl_is_retained_without_inventing_an_expiry(
    monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    case = guard_case(monkeypatch)
    proof = case.selected.proof
    policy = case.guard.reader.reader.rules.bundle_policy
    assert policy.freshness_seconds is None
    freshness = QualifiedFreshness(
        case.guard.template.source_metadata.artifact_id, policy, None, available
    )
    initial = replace(proof.initial, sources=replace(proof.initial.sources, freshness=(freshness,)))
    selected = replace(case.selected, proof=replace(proof, initial=initial))
    monkeypatch.setattr(case.guard.reader, "load_selected_locked", AsyncMock(return_value=selected))
    if not available:
        with pytest.raises(ValueError):
            await case.guard.disclosure_windows(case.session, case.control)
        return
    dates = await case.guard.disclosure_windows(case.session, case.control)
    assert all(date.utcoffset() is not None for date in dates)
    assert None not in dates


async def test_final_validate_rechecks_after_inherited_extra_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.builder import selected_strategy_guard as module

    case = guard_case(monkeypatch)

    async def actual_base(self: BuilderSourceGuard, *args: object) -> None:
        case.order.append("base-validate")
        self.deadlines = await self.disclosure_windows(case.session, case.control)

    monkeypatch.setattr(BuilderSourceGuard, "validate", actual_base)
    final = case.now + timedelta(seconds=60)
    clocks = AsyncMock(side_effect=[case.now, final])
    monkeypatch.setattr(module, "db_now", clocks)
    with pytest.raises(ValueError):
        await case.guard.validate(case.session, case.control, case.work, MagicMock(), case.now)
    assert case.order == ["base-validate", "base", "actor"] and clocks.await_count == 2


async def test_original_factory_identity_cannot_drift_after_guard_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    case.guard.artifacts.factory = MagicMock()
    with pytest.raises(ValueError):
        await case.guard.disclosure_windows(case.session, case.control)
    assert case.order == []


@pytest.mark.parametrize("drift", ["factory", "catalog", "input_reader"])
async def test_final_composite_clock_denies_configuration_drift_after_disclosure(
    monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    case = guard_case(monkeypatch)
    case.guard.deadlines = await case.guard.disclosure_windows(case.session, case.control)
    final = CompositeBeforeIntentCheck((case.guard,))
    final.validate_time(case.now)

    async def later_parent_or_flush_delivery() -> None:
        if drift == "factory":
            case.guard.artifacts.factory = MagicMock()
        elif drift == "catalog":
            case.guard.reader.reader.catalog = case.guard.reader.reader.catalog.model_copy(
                update={"cycle_admission": None}
            )
        else:
            case.guard.reader.reader = copy(case.guard.reader.reader)

    await later_parent_or_flush_delivery()
    with pytest.raises(ValueError, match="configuration or exact lease binding"):
        final.validate_time(case.now)


async def test_direct_disclosure_rechecks_composition_after_its_last_clock_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.builder import selected_strategy_guard as module

    case = guard_case(monkeypatch)

    async def clock_delivery(_session: object) -> datetime:
        case.guard.artifacts.factory = MagicMock()
        return case.now

    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=clock_delivery))
    with pytest.raises(ValueError, match="configuration or exact lease binding"):
        await case.guard.disclosure_windows(case.session, case.control)
