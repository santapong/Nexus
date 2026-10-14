"""Actual succeeded native engineering receipts recover protected proof without another effect."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_recovery_fixture import (
    engineering_recovery_factory as engineering_recovery_factory,
)
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_native_engineering_acceptance import _m1_facts
from nexus.tests.management_plan_support import VERIFIER


async def test_actual_succeeded_verifier_reconcile_finishes_proof_without_reissue(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    original = item.lease
    await item.runner.execution.release(original, identity(VERIFIER))
    job = item.verifier.spec.job
    scope = LedgerScope(
        company_id=job.company_id, principal_id=VERIFIER, task_id=job.task_id, trace_id=job.trace_id
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), original.segment_id
    )
    assert lease.mode == "reconcile" and lease.fence > original.fence
    before = await _m1_facts(engineering_recovery_factory)
    with pytest.raises(ExecutionDeniedError):
        await item.runner.execution.release(original, identity(VERIFIER))
    recovery = EngineeringAcceptanceRecovery(
        engineering_recovery_factory,
        item.catalog,
        item.acceptance.inputs,
        item.acceptance.proof,
    )
    record = await recovery.reconcile_verified_result(
        lease, identity(VERIFIER), verifier_action_id=job.action_id
    )
    assert record.verdict == "pass"
    assert await _m1_facts(engineering_recovery_factory) == before
    assert (
        await recovery.reconcile_verified_result(
            lease, identity(VERIFIER), verifier_action_id=job.action_id
        )
        == record
    )
    assert await _m1_facts(engineering_recovery_factory) == before
    await item.runner.execution.release(lease, identity(VERIFIER))


@pytest.mark.parametrize("reason", ["paused", "member", "source", "fence"])
async def test_current_recovery_authority_denial_preserves_native_facts(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    reason: str,
) -> None:
    # Keep the >50-line public fixture and one chosen denial together so unchanged
    # native receipts, attempts and held costs are checked against the same run.
    from uuid import UUID

    from nexus.company.control_store import CompanyControls
    from nexus.company.directory_contracts import MembershipChange
    from nexus.company.directory_store import PersistentCompanyDirectory
    from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
    from nexus.tests.integration.test_native_engineering_acceptance import (
        _acceptance_count,
        _change_read,
    )

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    job = item.verifier.spec.job
    scope = LedgerScope(
        company_id=job.company_id, principal_id=VERIFIER, task_id=job.task_id, trace_id=job.trace_id
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), item.lease.segment_id
    )
    before = await _m1_facts(engineering_recovery_factory)
    if reason == "paused":
        await CompanyControls(engineering_recovery_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    elif reason == "member":
        await PersistentCompanyDirectory(engineering_recovery_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=VERIFIER, role="member", membership_active=False
            ),
            control(),
        )
    elif reason == "source":
        assert item.author.spec.protected_patch is not None
        await _change_read(
            item,
            engineering_recovery_factory,
            item.author.spec.protected_patch,
            UUID(int=9501),
            active=False,
        )
    else:
        lease = lease.model_copy(update={"fence": lease.fence - 1})
    recovery = EngineeringAcceptanceRecovery(
        engineering_recovery_factory, item.catalog, item.acceptance.inputs, item.acceptance.proof
    )
    with pytest.raises(ValueError):
        await recovery.reconcile_verified_result(
            lease, identity(VERIFIER), verifier_action_id=job.action_id
        )
    assert await _acceptance_count(engineering_recovery_factory) == 0
    assert await _m1_facts(engineering_recovery_factory) == before


async def test_proof_resource_expiry_after_recovery_append_rolls_back_acceptance(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the >50-line real grant-expiry scenario and final-await instrumentation
    # together; splitting them could conceal whether the nominated boundary ran.
    from sqlalchemy import func, select

    import nexus.builder.engineering_acceptance_recovery as module
    from nexus.builder.engineering_inputs import PreparedEngineeringInput
    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.sources import ArtifactRevisionRef
    from nexus.execution.runtime_contracts import ExecutionLease
    from nexus.execution.runtime_models import ExecutionWork
    from nexus.execution.runtime_support import execution_row
    from nexus.tests.integration.test_native_engineering_acceptance import (
        _acceptance_count,
        _change_read,
    )

    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True
    )
    proof = await item.acceptance.prepare_verified_result(
        item.lease,
        identity(VERIFIER),
        author_action_id=item.author.spec.job.action_id,
        verifier_action_id=item.verifier.spec.job.action_id,
    )
    await _change_read(
        item,
        engineering_recovery_factory,
        proof,
        item.acceptance.proof.target.resource_id,
        active=True,
        seconds=5,
    )
    await item.runner.execution.release(item.lease, identity(VERIFIER))
    job = item.verifier.spec.job
    scope = LedgerScope(
        company_id=job.company_id, principal_id=VERIFIER, task_id=job.task_id, trace_id=job.trace_id
    )
    lease = await item.runner.execution.recover_dispatched(
        scope, identity(VERIFIER), uuid4(), item.lease.segment_id
    )
    recovery = EngineeringAcceptanceRecovery(
        engineering_recovery_factory, item.catalog, item.acceptance.inputs, item.acceptance.proof
    )
    before = await _m1_facts(engineering_recovery_factory)
    original = execution_row
    in_final = False
    delayed_count = 0
    final = recovery._final_time

    async def final_hook(
        session: AsyncSession,
        owned: ExecutionLease,
        selected: BrainReadScope,
        prepared: PreparedEngineeringInput,
        reference: ArtifactRevisionRef,
    ) -> None:
        nonlocal in_final
        in_final = True
        try:
            await final(session, owned, selected, prepared, reference)
        finally:
            in_final = False

    async def delayed(session: AsyncSession, selected: LedgerScope) -> ExecutionWork:
        nonlocal delayed_count
        value = await original(session, selected)
        if in_final:
            delayed_count += 1
            await session.execute(select(func.pg_sleep(5.3)))
        return value

    monkeypatch.setattr(recovery, "_final_time", final_hook)
    monkeypatch.setattr(module, "execution_row", delayed)
    with pytest.raises(ValueError):
        await recovery.reconcile_verified_result(
            lease, identity(VERIFIER), verifier_action_id=job.action_id
        )
    assert await _acceptance_count(engineering_recovery_factory) == 0
    assert delayed_count == 1
    assert await _m1_facts(engineering_recovery_factory) == before
