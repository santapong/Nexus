"""Protected actual-file discovery for crash recovery; no provider or database access."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.core.llm.company_pricing import quote_cost
from nexus.core.llm.qualification_contracts import financial_bounds
from nexus.execution import qualification_worker_recovery as module
from nexus.execution.qualification_worker_context import QualificationOperation
from nexus.harness.journal_budget import billing_day
from nexus.tests.unit.test_qualification_client import prepared
from nexus.tests.unit.test_qualification_worker import services


async def test_discovery_reads_actual_envelope_and_rejects_crossed_native_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    result = await client.request_once()
    assert result.evidence is not None and result.record is not None
    issued = await client._store.find_issued(client._request, result.record, end_us=client._end)
    assert issued is not None and issued.reference == result.evidence
    assert issued.evidence.request == client._request
    assert order == ["intent", "post", "receipt"]
    crossed = result.record.model_copy(update={"run_id": UUID(int=99)})
    with pytest.raises(ValueError):
        await client._store.find_issued(client._request, crossed, end_us=client._end)


async def test_discovery_absence_and_complete_hash_are_not_caller_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = prepared(tmp_path, monkeypatch)
    result = await client.request_once()
    assert result.evidence is not None and result.record is not None
    absent = client._request.model_copy(update={"request_id": UUID(int=99)})
    assert await client._store.find_issued(absent, result.record, end_us=client._end) is None
    path = Path(result.evidence.reference)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        await client._store.find_issued(client._request, result.record, end_us=client._end)


async def test_native_failed_replay_preserves_later_interruption_without_success_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, context = services(tmp_path, monkeypatch)
    (tmp_path / "actual").mkdir()
    client, order = prepared(tmp_path / "actual", monkeypatch)
    result = await client.request_once()
    assert result.record is not None and result.record.receipt is not None
    receipt = result.record.receipt.model_copy(update={"outcome": "failed"})
    native = result.record.model_copy(update={"state": "failed", "receipt": receipt})
    value = replace(value, evidence=client._store)
    context = replace(context, issued=native)
    monkeypatch.setattr(module, "revalidate_history", AsyncMock())
    hold = module.QualificationHoldFacts(
        native.company_id,
        native.task_id,
        native.action_id,
        billing_day(native.created_at),
        quote_cost(
            context.recipe.target.price, financial_bounds(context.recipe), now=native.created_at
        ).amount_usd,
        result.actual_usd,
        "reconciled",
    )
    monkeypatch.setattr(module, "_hold", AsyncMock(return_value=hold))
    replay = await module.recover_issued(QualificationOperation(value), context, end_us=client._end)
    assert replay is not None and replay.record == native
    assert order == ["intent", "post", "receipt"]  # No new SDK request.
    found = await client._store.find_issued(client._request, native, end_us=client._end)
    assert found is not None
    for crossed in (
        replace(hold, amount_usd=Decimal(0)),
        replace(hold, actual_usd=Decimal(0)),
        replace(hold, day=hold.day + timedelta(days=1)),
    ):
        with pytest.raises(ValueError):
            module.require_saved_result(context.recipe, context.request, native, found, crossed)
