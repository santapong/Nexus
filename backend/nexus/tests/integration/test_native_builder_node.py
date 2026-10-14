"""Actual M1 Node fixture verifies one finite process and honest baseline failure."""

import base64
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder import node_runner
from nexus.builder.node_runner import NodeNativeBuilderRunner
from nexus.builder.process import ProcessCapture, bounded_call
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.builder_node_support import node_factory as node_factory
from nexus.tests.builder_node_support import node_scenario
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def test_actual_node_m1_one_process_exec_scratch_neighbors_and_replay(
    node_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await node_scenario(node_factory, tmp_path)
    calls = 0

    async def counted(
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

    monkeypatch.setattr(node_runner, "bounded_call", counted)
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "commands_succeeded"
    assert len(result.commands) == 8 and len(result.artifacts) == 8
    assert result.observed_memory_max == 268435456 and result.observed_pids_max == 32
    logs = b"".join(base64.b64decode(row.content_base64) for row in result.logs)
    assert logs.count(b"actual_scratch_exec_ro_inputs_noexec_neighbors_no_host_mounts") == 2
    assert logs.count(b"actual_loopback_lookup_hosts_readonly_no_outside_aliases") == 2
    assert (
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        == result
    )
    assert calls == 1
    item.guard.identity = identity(OWNER)
    with pytest.raises(ValueError, match="another native execution"):
        await item.runner.reconcile(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    item.guard.identity = identity(ACTOR)
    await ResourceAccessStore(node_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=9901)),
            principal_id=ACTOR,
            active=False,
            expected_generation=1,
        ),
    )
    assert (
        await item.runner.reconcile(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
        is None
    )
    assert calls == 1


async def test_node_baseline_failure_has_actual_failed_receipt_no_post(
    node_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await node_scenario(node_factory, tmp_path, failed_baseline=True)
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "commands_failed"
    assert len(result.commands) == 2 and result.commands[-1].exit_code == 7
    assert all(row.phase == "baseline" for row in result.commands)
    async with runtime_transaction(node_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        row = await session.get(EffectIntent, (item.lease.company_id, item.action.action_id))
        assert row is not None and row.state == "failed" and row.receipt_json is not None
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 1


async def test_changed_public_cache_denies_before_intent_or_process(
    node_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await node_scenario(node_factory, tmp_path)
    assert isinstance(item.runner, NodeNativeBuilderRunner)
    item.runner.config.cache_archive.write_bytes(b"changed before intent")

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Changed public inputs must not launch a process")

    monkeypatch.setattr(node_runner, "bounded_call", forbidden)
    with pytest.raises(ValueError, match="bytes changed"):
        await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    async with runtime_transaction(node_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0
