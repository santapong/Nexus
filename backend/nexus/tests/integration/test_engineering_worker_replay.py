"""Actual same-dispatch known-output worker replay and acquired-lease cleanup boundaries."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.engineering_worker import execute_engineering_segment
from nexus.execution.engineering_worker_context import prepare_engineering_context
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_recovery_fixture import (
    engineering_recovery_factory as engineering_recovery_factory,
)
from nexus.tests.engineering_worker_fixture import worker_services
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_native_engineering_acceptance import _m1_facts
from nexus.tests.management_plan_support import VERIFIER


async def actual_command(
    factory: async_sessionmaker[AsyncSession], action_id: UUID
) -> SegmentCommand:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        dispatch = await session.get(SegmentDispatch, (COMPANY, action_id))
        assert dispatch is not None
        return SegmentCommand.model_validate_json(dispatch.binding_json)


async def test_source_resolver_failure_releases_actual_acquired_lease(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    command = await actual_command(engineering_recovery_factory, item.verifier.spec.job.action_id)
    before = await _m1_facts(engineering_recovery_factory)
    with pytest.raises(ValueError, match="source unavailable"):
        await prepare_engineering_context(
            worker_services(item, fail_source=True), command, workflow_id=command.workflow_id
        )
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=command.actor_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    actual = await item.runner.execution.get(scope, identity(VERIFIER))
    assert actual.worker_id is None and actual.expires_at is None
    assert await _m1_facts(engineering_recovery_factory) == before


async def test_actual_known_output_worker_returns_current_acceptance_and_releases_capacity(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    command = await actual_command(engineering_recovery_factory, item.verifier.spec.job.action_id)
    before = await _m1_facts(engineering_recovery_factory)
    result = await execute_engineering_segment(
        worker_services(item), command, workflow_id=command.workflow_id
    )
    assert (
        result.status == "accepted"
        and result.billing == "unconfirmed"
        and result.acceptance_id is not None
    )
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=command.actor_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    actual = await item.runner.execution.get(scope, identity(VERIFIER))
    assert actual.worker_id is None and actual.state == "verifying"
    assert await _m1_facts(engineering_recovery_factory) == before


async def test_sealed_credential_expiry_at_final_recovery_clock_rolls_back_acceptance(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep this >50-line actual public fixture, sealed credential and nominated
    # final-await hook together so the test cannot pass before reaching its gate.
    import asyncio
    from datetime import UTC, datetime

    from pydantic import SecretStr

    from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
    from nexus.builder.engineering_inputs import PreparedEngineeringInput
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.sources import ArtifactRevisionRef
    from nexus.company.management.plan_store import ManagementPlanStore
    from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
    from nexus.execution.runtime_contracts import ExecutionLease
    from nexus.tests.engineering_worker_fixture import TEST_SIGNING_KEY, FixtureWorkerCredential
    from nexus.tests.integration.test_native_engineering_acceptance import _acceptance_count

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    command = await actual_command(engineering_recovery_factory, item.verifier.spec.job.action_id)
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=VERIFIER,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), command.segment_id
    )
    async with engineering_recovery_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        selected = await ManagementPlanStore.current_binding(session, COMPANY, command.task_id)
        assert selected is not None
        expected = selected.child.binding
    provider = FixtureWorkerCredential(item, expires_seconds=3)
    credential = await NotificationWorkerIdentities(
        provider, SecretStr(TEST_SIGNING_KEY), enabled=True
    ).current(expected)
    recovery = EngineeringAcceptanceRecovery(
        engineering_recovery_factory,
        item.catalog,
        item.acceptance.inputs,
        item.acceptance.proof,
        credential=credential,
    )
    before = await _m1_facts(engineering_recovery_factory)
    original = recovery._final_time
    calls = 0

    async def expire(
        session: AsyncSession,
        owned: ExecutionLease,
        selected: BrainReadScope,
        prepared: PreparedEngineeringInput,
        reference: ArtifactRevisionRef,
    ) -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(
            max(0, (credential.expires_at - datetime.now(UTC)).total_seconds()) + 0.03
        )
        await original(session, owned, selected, prepared, reference)

    monkeypatch.setattr(recovery, "_final_time", expire)
    with pytest.raises(ValueError):
        await recovery.reconcile_verified_result(
            lease, identity(VERIFIER), verifier_action_id=command.action_id
        )
    assert calls == 1 and await _acceptance_count(engineering_recovery_factory) == 0
    assert await _m1_facts(engineering_recovery_factory) == before


async def test_verified_foreign_credential_cannot_record_lease_actor_acceptance(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    # Keep the >50-line actual known-receipt fixture and independently verified
    # foreign token in one scenario; no raw witness or acceptance is fabricated.
    from datetime import UTC, datetime

    import jwt
    from pydantic import SecretStr

    from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
    from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
    from nexus.tests.engineering_worker_fixture import TEST_SIGNING_KEY
    from nexus.tests.integration.test_company_directory import ACTOR, WORKSPACE
    from nexus.tests.integration.test_native_engineering_acceptance import _acceptance_count
    from nexus.tests.unit.test_company_notification_worker_identity import FixtureCredential

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    command = await actual_command(engineering_recovery_factory, item.verifier.spec.job.action_id)
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=VERIFIER,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), command.segment_id
    )
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"sub": str(ACTOR), "workspace_id": str(WORKSPACE), "iat": now - 1, "exp": now + 300},
        TEST_SIGNING_KEY,
        algorithm="HS256",
    )
    witness = await NotificationWorkerIdentities(
        FixtureCredential(SecretStr(token)), SecretStr(TEST_SIGNING_KEY), enabled=True
    ).current()
    recovery = EngineeringAcceptanceRecovery(
        engineering_recovery_factory,
        item.catalog,
        item.acceptance.inputs,
        item.acceptance.proof,
        credential=witness,
    )
    before = await _m1_facts(engineering_recovery_factory)
    with pytest.raises(ValueError):
        await recovery.reconcile_verified_result(
            lease, identity(VERIFIER), verifier_action_id=command.action_id
        )
    assert await _acceptance_count(engineering_recovery_factory) == 0
    assert await _m1_facts(engineering_recovery_factory) == before
