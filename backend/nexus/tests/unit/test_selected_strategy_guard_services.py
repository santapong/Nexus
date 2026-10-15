"""The concrete factory keeps final subclass behavior and validates unselected configuration."""

from dataclasses import replace
from typing import cast

import pytest

from nexus.builder.selected_strategy_guard import StrategySelectedBuilderGuard
from nexus.builder.selected_strategy_services import SelectedBuilderServices
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.tests.unit.selected_strategy_guard_fixture import guard_case


def test_factory_returns_final_concrete_guard_with_separate_per_job_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    other = case.services.resolve_guard(case.original, case.guard.credential)
    assert type(other) is type(case.guard) is StrategySelectedBuilderGuard
    assert other is not case.guard and other.reader is case.guard.reader
    with pytest.raises(ValueError):
        other.validate_time(case.now)


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "duplicate",
        "foreign_binding",
        "unselected_template",
        "raw_limit",
        "foreign_dependency",
    ],
)
def test_complete_configuration_denies_before_selection(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = guard_case(monkeypatch)
    entries = case.services.entries
    if change == "empty":
        entries = ()
    elif change == "duplicate":
        entries = (entries[0], entries[0])
    elif change == "foreign_binding":
        entries = (entries[0], replace(entries[1], binding=entries[0].binding))
    elif change == "unselected_template":
        entries = (
            entries[0],
            replace(
                entries[1],
                template=entries[1].template.model_copy(
                    update={"candidate_scope_sha256": "f" * 64}
                ),
            ),
        )
    elif change == "raw_limit":
        entries = (
            entries[0],
            replace(
                entries[1],
                template=entries[1].template.model_copy(
                    update={
                        "limits": entries[1].template.limits.model_copy(
                            update={"command_seconds": True}
                        )
                    }
                ),
            ),
        )
    else:
        case.guard.reader.reader.catalog = case.guard.reader.reader.catalog.model_copy(
            update={"cycle_admission": None}
        )
    with pytest.raises(ValueError):
        SelectedBuilderServices(case.guard.reader, entries)


def test_bare_identity_and_foreign_source_composition_cannot_construct_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = guard_case(monkeypatch)
    with pytest.raises(ValueError):
        case.services.resolve_guard(
            case.original, cast(AuthenticatedWorkerIdentity, case.original.identity)
        )
    case.original.freshness = object()  # type: ignore[assignment]
    with pytest.raises(ValueError):
        case.services.resolve_guard(case.original, case.guard.credential)
    assert case.order == []
