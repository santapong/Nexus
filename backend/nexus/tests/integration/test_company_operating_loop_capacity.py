"""Expired unissued verifier preparation capacity is recovered without a second draft/effect."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.management.native_loop_store import NativeReportOperatingLoop
from nexus.execution.native_report_worker import execute_native_report
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_operating_loop import queued_command
from nexus.tests.operating_loop_support import configured_loop, decide_existing
from nexus.tests.operating_loop_support import loop_factory as loop_factory


async def test_expired_unissued_verifier_capacity_recovers_into_same_pending_wait(
    loop_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path)
    author = await loop.tick(control(), identity(OWNER))
    assert author.pending
    await decide_existing(loop_factory, author.pending)
    queued = await loop.tick(control(), identity(OWNER))
    assert queued.scheduled and queued.scheduled.workflow_id
    command = await queued_command(loop_factory, queued.scheduled.workflow_id)
    assert (
        await execute_native_report(case.native, command, workflow_id=command.workflow_id)
    ).status == "published"
    loop = NativeReportOperatingLoop(
        loop.registration, case.preparation, replace(case.native, lease_ttl_seconds=8)
    )
    original = ExecutionStore.await_approval
    reached = False

    async def expired_wait(
        store: ExecutionStore, lease: ExecutionLease, signed: VerifiedIdentity, action_id: UUID
    ) -> ExecutionSnapshot:
        nonlocal reached
        reached = True
        await asyncio.sleep(max(0, (lease.expires_at - datetime.now(UTC)).total_seconds()) + 0.1)
        return await original(store, lease, signed, action_id)

    monkeypatch.setattr(ExecutionStore, "await_approval", expired_wait)
    interrupted = await loop.tick(control(), identity(OWNER))
    assert reached and interrupted.state == "blocked"
    verifier = case.payload.children[1].binding
    expired = await case.native.execution.get(ledger(verifier), identity(verifier.actor_id))
    assert (
        expired.worker_id is not None
        and expired.expires_at
        and expired.expires_at <= datetime.now(UTC)
    )
    monkeypatch.setattr(ExecutionStore, "await_approval", original)
    resumed = await loop.tick(control(), identity(OWNER))
    assert (
        resumed.state == "verifier_pending"
        and resumed.pending
        and not resumed.preparation_performed
    )
    assert resumed.pending.proposal.action_id == loop.registration.action_id("verifier")
    current = await case.native.execution.get(ledger(verifier), identity(verifier.actor_id))
    assert (
        current.worker_id is None
        and current.expires_at is None
        and current.state == "awaiting_approval"
    )
    assert current.counters == expired.counters and current.registration == expired.registration
    before = await saved_m1(loop_factory)
    assert (await loop.tick(control(), identity(OWNER))).state == "verifier_pending"
    assert await saved_m1(loop_factory) == before
