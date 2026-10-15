"""Two-phase C publication with mocked gates; actual PG qualification remains pending."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.strategy import check_store as module
from nexus.company.strategy.artifact_identity import strategy_reference
from nexus.company.strategy.check_actor import StrategyIssuedCheck
from nexus.company.strategy.check_store import StrategyCheckStore
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.tests.unit.strategy_check_rows_fixture import rows_case
from nexus.tests.unit.strategy_verifier_receipt_fixture import receipt_case


@pytest.mark.parametrize("failure", [None, "blob", "gate2", "time1", "time2"])
async def test_check_store_preserves_first_and_current_windows_after_final_flush(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    # Keep this >50-line fixture's initial/current windows and failure order together.
    receipt = receipt_case(monkeypatch)
    rows = rows_case(monkeypatch)
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    order: list[str] = []

    async def flush() -> None:
        order.append("flush")

    session.flush = AsyncMock(side_effect=flush)
    factory = cast(async_sessionmaker[AsyncSession], object())
    blobs = MagicMock(spec=BrainBlobStore)
    blobs.storage_symbol = "fixture.blobs.v1"

    async def save(*_: object) -> None:
        order.append("blob")
        if failure == "blob":
            raise OSError("nominated blob failure")

    blobs.save = AsyncMock(side_effect=save)
    reader = MagicMock(spec=StrategyInputReader)
    reader.artifacts = SimpleNamespace(factory=factory, blobs=blobs)
    reader.rules = SimpleNamespace(check=rows.rule, check_policy=rows.policy)
    store = StrategyCheckStore(factory, blobs, reader)
    calls = {"gate": 0}

    class Protection:
        def __init__(self, name: str) -> None:
            self.name = name

        def require_time(self, _: object) -> None:
            order.append(self.name)
            if failure == self.name:
                raise AcceptanceDeniedError("nominated expired window")

    async def gate(*_: object, **__: object) -> StrategyIssuedCheck:
        calls["gate"] += 1
        order.append(f"gate{calls['gate']}")
        if failure == f"gate{calls['gate']}":
            raise AcceptanceDeniedError("nominated current gate denial")
        return cast(
            StrategyIssuedCheck, SimpleNamespace(protection=Protection(f"time{calls['gate']}"))
        )

    @asynccontextmanager
    async def transaction(
        *_: object, **__: object
    ) -> AsyncIterator[tuple[AsyncSession, object, object]]:
        yield cast(AsyncSession, session), receipt.control, receipt.clock["now"]

    async def write(*_: object) -> None:
        order.append("rows")

    async def replay(*_: object) -> None:
        order.append("graph")

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    monkeypatch.setattr(module, "revalidate_strategy_check_actor_locked", gate)
    monkeypatch.setattr(module, "write_strategy_check_locked", write)
    monkeypatch.setattr(module, "execution_row", AsyncMock(return_value=receipt.work))
    monkeypatch.setattr(module, "db_now", AsyncMock(return_value=receipt.clock["now"]))
    monkeypatch.setattr(store, "_replay", replay)

    async def publish() -> object:
        return await store.publish_check(
            receipt.lease,
            receipt.credential.identity,
            rows.action_id,
            rows.prepared,
            credential=receipt.credential,
        )

    if failure is not None:
        with pytest.raises((OSError, AcceptanceDeniedError)):
            await publish()
        complete = ["gate1", "blob", "gate2", "rows", "graph", "flush", "time1", "time2"]
        assert order == complete[: complete.index(failure) + 1]
        return
    result = await publish()
    assert result == strategy_reference(rows.prepared, rows.action_id)
    assert order == ["gate1", "blob", "gate2", "rows", "graph", "flush", "time1", "time2"]


def test_store_cannot_mix_reader_and_blob_storage() -> None:
    factory = cast(async_sessionmaker[AsyncSession], object())
    blobs = MagicMock(spec=BrainBlobStore)
    reader = MagicMock(spec=StrategyInputReader)
    reader.artifacts = SimpleNamespace(factory=factory, blobs=object())
    with pytest.raises(ValueError, match="factory/storage"):
        StrategyCheckStore(factory, blobs, reader)
