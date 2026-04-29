"""Tests for the optional demo data seeded for fresh-clone UAT walkthroughs."""

from __future__ import annotations

import pytest


def test_demo_tasks_have_workspace_safe_shape() -> None:
    """The two seeded demo tasks must have non-empty instructions and dict outputs.

    The dashboard expects ``output`` to be a JSON object — a string or None
    would render incorrectly on the task detail page.
    """
    from nexus.db.seed import _DEMO_TASKS

    assert len(_DEMO_TASKS) == 2
    for instruction, output in _DEMO_TASKS:
        assert isinstance(instruction, str) and instruction.strip()
        assert isinstance(output, dict) and output


def test_demo_seed_function_is_present() -> None:
    """The demo seed entry point exists and is async-callable."""
    import inspect

    from nexus.db.seed import _seed_demo_workspace

    assert inspect.iscoroutinefunction(_seed_demo_workspace)


def test_seed_main_respects_demo_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """``seed()`` only invokes ``_seed_demo_workspace`` when NEXUS_SEED_DEMO is truthy."""
    from nexus.db import seed as seed_mod

    calls = {"demo": 0, "agents": 0, "prompts": 0, "benchmarks": 0, "schedules": 0}

    async def _record_demo(_session: object) -> None:
        calls["demo"] += 1

    async def _record_agents(_session: object) -> None:
        calls["agents"] += 1

    async def _record_prompts(_session: object) -> None:
        calls["prompts"] += 1

    async def _record_benchmarks(_session: object) -> None:
        calls["benchmarks"] += 1

    async def _record_schedules(_session: object) -> None:
        calls["schedules"] += 1

    monkeypatch.setattr(seed_mod, "_seed_demo_workspace", _record_demo)
    monkeypatch.setattr(seed_mod, "_seed_agents", _record_agents)
    monkeypatch.setattr(seed_mod, "_seed_prompts", _record_prompts)
    monkeypatch.setattr(seed_mod, "_seed_benchmarks", _record_benchmarks)
    monkeypatch.setattr(seed_mod, "_seed_schedules", _record_schedules)

    # Stub out the engine + session machinery so we don't touch a real DB.
    import contextlib
    from unittest.mock import AsyncMock, MagicMock

    fake_session = MagicMock()
    fake_session.commit = AsyncMock()

    @contextlib.asynccontextmanager
    async def _ctx() -> object:
        yield fake_session

    fake_factory = MagicMock(return_value=_ctx())

    monkeypatch.setattr(seed_mod, "create_async_engine", lambda _url: AsyncMock())
    monkeypatch.setattr(seed_mod, "async_sessionmaker", lambda *_a, **_kw: fake_factory)

    # Demo flag OFF — should not call the demo seeder.
    monkeypatch.delenv("NEXUS_SEED_DEMO", raising=False)
    import asyncio

    asyncio.run(seed_mod.seed())
    assert calls["demo"] == 0
    assert calls["agents"] == 1

    # Demo flag ON — must call the demo seeder.
    monkeypatch.setenv("NEXUS_SEED_DEMO", "true")
    fake_factory.return_value = _ctx()  # fresh context manager
    asyncio.run(seed_mod.seed())
    assert calls["demo"] == 1
    assert calls["agents"] == 2
