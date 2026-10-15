"""Exact C graph/edge replay tests; transaction rollback and RLS still require native PG proof."""

from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy import check_rows as module
from nexus.tests.unit.strategy_check_rows_fixture import CheckRowsCase, rows_case


async def _replay(case: CheckRowsCase) -> None:
    await module.require_strategy_check_replay_locked(
        case.session, case.scope, case.action_id, case.prepared, case.rule, "fixture.blobs.v1"
    )


async def test_exact_check_graph_returns_without_appending(monkeypatch: pytest.MonkeyPatch) -> None:
    case = rows_case(monkeypatch)
    await _replay(case)
    case.session.add.assert_not_called()
    case.session.add_all.assert_not_called()


@pytest.mark.parametrize("group", range(4))
@pytest.mark.parametrize("change", ["missing", "extra"])
async def test_each_graph_edge_group_is_exact(
    monkeypatch: pytest.MonkeyPatch, group: int, change: str
) -> None:
    case = rows_case(monkeypatch)
    if change == "missing":
        case.edges[group].pop()
    else:
        case.edges[group].append(UUID(int=999))
    with pytest.raises(AcceptanceDeniedError):
        await _replay(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_text", "changed"),
        ("resource_id", UUID(int=999)),
        ("storage_symbol", "other"),
        ("data_classification", "public"),
        ("derivation_id", UUID(int=999)),
    ],
)
async def test_wrong_native_result_metadata_denies(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = rows_case(monkeypatch)
    setattr(case.artifact, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _replay(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_recipe", "fake-model"),
        ("recipe_version", "wrong"),
        ("kind", "summary"),
        ("artifact_revision_id", UUID(int=999)),
    ],
)
async def test_check_derivation_cannot_be_replaced(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = rows_case(monkeypatch)
    setattr(case.derivation, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _replay(case)


async def test_derivation_time_cannot_be_spliced_from_another_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = rows_case(monkeypatch)
    case.derivation.recorded_at += timedelta(seconds=1)
    with pytest.raises(AcceptanceDeniedError):
        await _replay(case)


async def test_event_identity_must_be_the_original_writer_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = rows_case(monkeypatch)
    case.event.event_id = UUID(int=999)
    with pytest.raises(AcceptanceDeniedError):
        await _replay(case)


@pytest.mark.parametrize(
    "field,value",
    [("kind", "source_changed"), ("action_id", UUID(int=999)), ("resource_id", UUID(int=999))],
)
async def test_original_check_event_must_match(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    case = rows_case(monkeypatch)
    setattr(case.event, field, value)
    with pytest.raises(AcceptanceDeniedError):
        await _replay(case)


async def test_append_creates_one_result_graph_with_complete_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = rows_case(monkeypatch)
    case.session.get.return_value = None
    case.session.get.side_effect = None
    await module.write_strategy_check_locked(
        case.session,
        case.scope,
        case.action_id,
        case.prepared,
        case.rule,
        case.policy,
        "fixture.blobs.v1",
        case.now,
    )
    assert case.session.add.call_count == 1 and case.session.add_all.call_count == 2
    module.validate_derivation.assert_awaited_once()  # type: ignore[attr-defined]
    module.save_derivation.assert_awaited_once()  # type: ignore[attr-defined]
    module.append_event.assert_awaited_once()  # type: ignore[attr-defined]
