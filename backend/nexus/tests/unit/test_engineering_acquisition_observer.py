"""Trusted process observer records live native preflight and delegates the original wait."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nexus.tests.engineering_acquisition_observer import install_acquisition_observer
from nexus.tests.unit.test_engineering_lease_recovery import inputs


async def test_test_observer_does_not_replace_preflight_or_wait_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.execution.engineering_lease_recovery as runtime
    import nexus.tests.engineering_acquisition_observer as observed

    services, scope, credential, command, lease = await inputs()
    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=30)
    prior = AsyncMock(return_value=deadline)
    waiting = AsyncMock()
    monkeypatch.setattr(runtime, "prior_live_deadline", prior)
    monkeypatch.setattr(runtime, "wait_prior", waiting)
    session = SimpleNamespace(scalar=AsyncMock(return_value="exact_fixture"))

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[object, object, object]]:
        yield session, object(), object()

    monkeypatch.setattr(observed, "runtime_transaction", transaction)
    monkeypatch.setattr(
        observed,
        "execution_row",
        AsyncMock(return_value=SimpleNamespace(worker_id=lease.worker_id, fence=1)),
    )
    monkeypatch.setattr(observed, "db_now", AsyncMock(return_value=now))
    install_acquisition_observer(tmp_path)
    assert await runtime.prior_live_deadline(services, scope, credential, command) == deadline
    await runtime.wait_prior(1.0)
    prior.assert_awaited_once_with(services, scope, credential, command)
    waiting.assert_awaited_once_with(1.0)
    rows = [
        json.loads(x)
        for x in (tmp_path / "acquisition-observations.jsonl").read_text().splitlines()
    ]
    assert (
        rows[0]["pid"] == os.getpid()
        and rows[0]["still_live"] is True
        and rows[0]["command"] == command.model_dump(mode="json")
    )
    assert rows[1] == {"event": "acquisition_wait", "pid": os.getpid(), "seconds": 1.0}
    assert credential.identity.principal_id.hex in str(rows[0]["actor_id"]).replace("-", "")
