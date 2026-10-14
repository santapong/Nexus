"""Trusted watch composition uses the actual current_source producer; no process runs."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.builder import contained_watch as module
from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.builder.runner_capture import LeaseWatch
from nexus.tests.unit.test_contained_spawn_window import window


@pytest.mark.parametrize("missing", [False, True])
async def test_final_spawn_watch_uses_current_renewed_lease_and_fixed_end(
    monkeypatch: pytest.MonkeyPatch,
    missing: bool,
) -> None:
    base = MagicMock(spec=LeaseWatch)
    base.factory, base.identity, base.action = MagicMock(), MagicMock(), MagicMock()
    base.guard = MagicMock()
    base.guard.lease = MagicMock()
    base.check = AsyncMock()
    current = AsyncMock(return_value=None if missing else window())
    monkeypatch.setattr(module, "current_source", current)
    watch = module.ContainedSourceWatch(cast(LeaseWatch, base), operation_end_us=9_000_000)
    if missing:
        with pytest.raises(ValueError, match="source window"):
            await watch.before_spawn()
    else:
        result = await watch.before_spawn()
        assert isinstance(result, SpawnWindow)
    base.check.assert_awaited_once()
    current.assert_awaited_once_with(
        base.factory,
        base.guard.lease,
        base.identity,
        base.action,
        base.guard,
        issued=True,
        operation_end_us=9_000_000,
    )


async def test_ongoing_watch_remains_existing_native_check() -> None:
    base = MagicMock(spec=LeaseWatch)
    base.check = AsyncMock()
    watch = module.ContainedSourceWatch(cast(LeaseWatch, base), operation_end_us=9_000_000)
    await watch.check()
    base.check.assert_awaited_once()
