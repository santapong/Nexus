"""Neutral material captures immutable fence/time observations; no actor permission is inferred."""

from dataclasses import replace
from datetime import timedelta

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy.current_proof_read import assemble_strategy_current_proof
from nexus.tests.unit.strategy_current_proof_fixture import proof_case


async def test_material_keeps_completed_fence_even_if_live_orm_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    first = await case.service._read(
        case.session,
        case.base.source.control,
        case.scope,
        case.credential.identity,
        case.selection,
        case.credential,
    )
    captured = first.author_current_fence
    first.material.protection.pair.author.fence += 1
    assert first.author_current_fence == captured
    current = replace(first, author_current_fence=captured + 1)
    with pytest.raises(AcceptanceDeniedError):
        assemble_strategy_current_proof(
            case.selection,
            first,
            current,
            case.credential,
            case.scope,
            case.credential.identity,
            case.base.source.clock["now"],
        )


async def test_neutral_assembly_rejects_backward_capture_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = proof_case(monkeypatch)
    first = await case.service._read(
        case.session,
        case.base.source.control,
        case.scope,
        case.credential.identity,
        case.selection,
        case.credential,
    )
    with pytest.raises(AcceptanceDeniedError):
        assemble_strategy_current_proof(
            case.selection,
            first,
            replace(first, observed_at=first.observed_at - timedelta(microseconds=1)),
            case.credential,
            case.scope,
            case.credential.identity,
            case.base.source.clock["now"],
        )
