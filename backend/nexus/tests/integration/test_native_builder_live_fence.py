"""Live source revocation stops the one issued process and never grants a replay call."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder import runner as runner_module
from nexus.builder.process import ProcessCapture, bounded_call
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.builder_runtime_support import builder_factory as builder_factory
from nexus.tests.builder_runtime_support import scenario
from nexus.tests.integration.test_company_directory import ACTOR
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_native_builder_boundaries import change_source


async def test_live_source_revoke_keeps_unknown_intent_and_no_repeat_command(
    builder_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await scenario(builder_factory, tmp_path, argv=("/bin/sh", "-c", "sleep 4"))
    started = asyncio.Event()
    calls = 0

    async def observed(
        argv: tuple[str, ...],
        *,
        name: str,
        action_id: str,
        company_id: str,
        seconds: int,
        stdout_limit: int,
        stderr_limit: int,
        watchdog: Callable[[], Awaitable[None]],
    ) -> ProcessCapture:
        nonlocal calls
        calls += 1
        started.set()
        return await bounded_call(
            argv,
            name=name,
            action_id=action_id,
            company_id=company_id,
            seconds=seconds,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
            watchdog=watchdog,
        )

    monkeypatch.setattr(runner_module, "bounded_call", observed)
    task = asyncio.create_task(
        item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    )
    await asyncio.wait_for(started.wait(), timeout=10)
    await change_source(builder_factory, ACTOR, active=False)
    assert await asyncio.wait_for(task, timeout=15) is None
    saved = await item.runner.results.load(item.spec)
    assert saved is not None and saved.outcome == "outcome_unknown"
    assert (
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        is None
        and calls == 1
    )
    async with runtime_transaction(builder_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        intent = await session.get(EffectIntent, (item.lease.company_id, item.action.action_id))
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None
