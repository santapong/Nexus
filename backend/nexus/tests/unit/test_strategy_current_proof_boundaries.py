"""Current-proof author state and private body ordering; no historical audit scope is changed."""

from unittest.mock import AsyncMock

import pytest

from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy import input_reader as module
from nexus.tests.unit.strategy_publication_reader_fixture import ReaderCase, reader_case


async def read(case: ReaderCase) -> None:
    await case.reader.load_original_locked(
        case.source.session,
        case.source.control,
        case.source.scope,
        case.source.credential.identity,
        case.prepared.action_id,
        credential=case.source.credential,
    )


@pytest.mark.parametrize("state", ["outcome_unknown", "blocked"])
async def test_succeeded_selected_receipt_does_not_make_blocked_or_unknown_author_current(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    case = reader_case(monkeypatch)
    pair = module.resolve_strategy_pair_locked  # type: ignore[attr-defined]
    assert isinstance(pair, AsyncMock)
    pair.return_value.author.state = state
    assert case.effect.state == "succeeded"
    with pytest.raises(AcceptanceDeniedError):
        await read(case)


async def test_denied_actual_artifact_read_precedes_any_full_private_bundle_body_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = reader_case(monkeypatch)
    gate = case.reader.artifacts.revalidate_artifact_reference
    assert isinstance(gate, AsyncMock)
    gate.side_effect = AcceptanceDeniedError("denied current artifact READ")
    with pytest.raises(AcceptanceDeniedError):
        await read(case)
    body_gets = [
        call for call in case.row_get.await_args_list if call.args[0] is BrainArtifactRevision
    ]
    assert body_gets == []
