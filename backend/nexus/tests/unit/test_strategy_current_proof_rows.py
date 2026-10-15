"""Exact selected proof rows, never latest-success selection or a write-on-read repair."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy.current_proof_rows import load_selected_acceptance_locked
from nexus.tests.unit.strategy_current_proof_rows_fixture import selected_case


@pytest.mark.parametrize(
    "change", [None, "missing", "extra", "hash", "foreign", "timestamp", "invalidated", "selection"]
)
async def test_selected_proof_exact_rows_and_invalidation(
    monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    case = selected_case(monkeypatch)
    if change == "missing":
        case.proofs.clear()
    elif change == "extra":
        case.proofs.append(case.proofs[0])
    elif change == "hash":
        case.proofs[0].artifact_sha256 = "b" * 64
    elif change == "foreign":
        case.proofs[0].company_id = UUID(int=999)
    elif change == "timestamp":
        case.row.recorded_at += timedelta(seconds=1)
    elif change == "invalidated":
        case.session.scalar = AsyncMock(return_value=UUID(int=999))
    elif change == "selection":
        case.selection = case.selection.model_copy(update={"acceptance_id": UUID(int=999)})
    if change is None:
        assert await load_selected_acceptance_locked(case.session, case.selection) == case.record
    else:
        with pytest.raises(AcceptanceDeniedError):
            await load_selected_acceptance_locked(case.session, case.selection)
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()
