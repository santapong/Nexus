"""Actual native cleanup fence expiry denies removal without rewriting known receipts or costs."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_cleanup import (
    CapturedOwnedContainer,
    cleanup_known_engineering_container,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_recovery_fixture import (
    engineering_recovery_factory as engineering_recovery_factory,
)
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_native_engineering_acceptance import _m1_facts
from nexus.tests.management_plan_support import VERIFIER


async def test_actual_final_cleanup_lease_expiry_denies_id_removal(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the >50-line actual public fixture and final lease-expiry injection
    # together so the nominated removal fence and unchanged native facts are proven.
    import nexus.builder.engineering_cleanup as module

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    result = item.verifier
    job = result.spec.job
    scope = LedgerScope(
        company_id=job.company_id, task_id=job.task_id, trace_id=job.trace_id, principal_id=VERIFIER
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), item.lease.segment_id, ttl_seconds=2
    )
    publisher = item.runner.publisher
    assert isinstance(publisher, EngineeringArtifactPublisher)
    await publisher.prepare_witness(result)
    receipt = item.runner.receipt(result, publisher.reference(result))
    before = await _m1_facts(engineering_recovery_factory)
    calls = 0

    async def captured(name: str, action: str, company: str, image: str) -> CapturedOwnedContainer:
        return CapturedOwnedContainer(
            "a" * 64, str(job.action_id), str(job.company_id), result.image_id
        )

    async def delay(capture: CapturedOwnedContainer) -> None:
        nonlocal calls
        calls += 1
        async with engineering_recovery_factory() as session:
            await session.execute(select(func.pg_sleep(2.2)))

    async def forbidden(argv: tuple[str, ...], limit: int = 16384) -> bytes:
        raise AssertionError("Expired cleanup issued Podman removal")

    monkeypatch.setattr(module, "inspect_owned_stopped", captured)
    monkeypatch.setattr(module, "require_captured_stopped", delay)
    monkeypatch.setattr(module, "owned_engine", forbidden)
    with pytest.raises(ValueError):
        await cleanup_known_engineering_container(
            engineering_recovery_factory,
            lease,
            identity(VERIFIER),
            item.verifier_action,
            result.spec,
            result,
            receipt,
        )
    assert calls == 1 and await _m1_facts(engineering_recovery_factory) == before


async def test_known_engineering_reconcile_hook_missing_container_is_idempotent(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.engineering_cleanup as module

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    job = item.verifier.spec.job
    scope = LedgerScope(
        company_id=job.company_id, task_id=job.task_id, trace_id=job.trace_id, principal_id=VERIFIER
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), item.lease.segment_id
    )
    original = item.verifier_guard
    from nexus.builder.source_guard import BuilderSourceGuard

    guard = BuilderSourceGuard(
        item.verifier.spec,
        original.policy,
        lease,
        original.identity,
        original.source,
        original.artifacts,
        original.freshness,
        original.catalog,
    )
    before = await _m1_facts(engineering_recovery_factory)
    calls = []

    async def empty(argv: tuple[str, ...], limit: int = 16384) -> bytes:
        calls.append(argv)
        assert argv[0] == "ps"
        return b""

    monkeypatch.setattr(module, "owned_engine", empty)
    result = await item.runner.reconcile(
        lease, identity(VERIFIER), item.verifier_action, item.verifier.spec, guard
    )
    assert result == item.verifier and len(calls) == 1
    assert await _m1_facts(engineering_recovery_factory) == before
    await item.runner.execution.release(lease, identity(VERIFIER))
