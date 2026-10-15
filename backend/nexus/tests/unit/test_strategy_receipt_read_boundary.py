"""The actual outer acceptance path must not fetch C bodies before complete READ."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.strategy import acceptance_store as module
from nexus.company.strategy.acceptance_store import StrategyAcceptanceStore
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.tests.unit.strategy_verifier_receipt_fixture import receipt_case


async def test_outer_acceptance_denied_c_read_never_fetches_full_c_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the unchanged public store rather than an unimplemented helper signature.
    case = receipt_case(monkeypatch)
    factory = cast(async_sessionmaker[AsyncSession], object())
    artifacts = MagicMock(spec=BoundedArtifactReader)
    artifacts.factory = factory
    artifacts.revalidate_artifact_reference = AsyncMock(side_effect=BrainDeniedError("no READ"))
    reader = MagicMock(spec=StrategyInputReader)
    reader.artifacts = artifacts
    reader.rules = SimpleNamespace(check=case.rule)
    reader.load_check_locked = AsyncMock(
        return_value=SimpleNamespace(command=SimpleNamespace(target=case.target))
    )
    reader.protect_check_result_locked = AsyncMock(side_effect=BrainDeniedError("no READ"))
    case.session.scalar = AsyncMock(return_value=False)
    full_bodies: list[object] = []
    original = case.session.get.side_effect

    async def get(model: object, key: object) -> object:
        if model is BrainArtifactRevision:
            full_bodies.append(key)
        return await original(model, key)

    case.session.get.side_effect = get

    @asynccontextmanager
    async def transaction(
        *_: object, **__: object
    ) -> AsyncIterator[tuple[AsyncSession, object, object]]:
        yield cast(AsyncSession, case.session), case.control, case.clock["now"]

    monkeypatch.setattr(module, "runtime_transaction", transaction)
    store = StrategyAcceptanceStore(factory, reader)
    with pytest.raises(BrainDeniedError, match="no READ"):
        await store.publish_verified_result(
            case.lease,
            case.credential.identity,
            author_action_id=case.target.action_id,
            verifier_action_id=case.action.action_id,
            protected_result=case.reference,
            credential=case.credential,
        )
    assert full_bodies == [], "full protected C body was fetched before READ denied"
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()
