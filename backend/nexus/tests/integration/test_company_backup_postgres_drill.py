"""Actual source→empty target native+DBOS restore and target-only unknown-workflow recovery."""

import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.control_store import CompanyControls
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.operations.backup_artifacts import restored_namespace
from nexus.operations.backup_capture import OperatorBackupCoordinator
from nexus.operations.backup_capture_contracts import RestoredCapture, SealedCapture
from nexus.operations.backup_drain import OwnedWorkerDrain
from nexus.tests.backup_drill_evidence import (
    RecoveryDrillEvidence,
    RecoveryFacts,
    assert_no_issuance_phases,
    assert_unknown_conserved,
    recovery_facts,
)
from nexus.tests.backup_postgres_fixture import (
    SOURCE,
    TARGET,
    BackupDatabase,
    backup_database,
    local_url,
)
from nexus.tests.backup_process_fixture import spawn_backup_worker
from nexus.tests.generated_artifact_fixture import GeneratedScenario, ledger
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_process_config import save_process_config
from nexus.tests.native_process_support import completed_native, enqueue_check, wait_barrier
from nexus.tests.native_workflow_support import prepare_check_dispatch, published_author

__all__ = ["backup_database"]


class EphemeralKey:
    """Synthetic encryption key remains only in the drill process, never persisted or logged."""

    def __init__(self) -> None:
        self._value = os.urandom(32)

    async def key(self) -> bytes:
        """Supply the separately injected transient key to the operator coordinator."""
        return self._value


async def test_actual_matching_native_dbos_restore_then_target_unknown_recovery(
    backup_database: BackupDatabase, tmp_path: Path
) -> None:
    factory = backup_database.factory
    source_root = tmp_path / "source-worker"
    source_root.mkdir(mode=0o700)
    scenario, command = await source_dispatch(factory, source_root)
    worker_id = uuid4()
    process = await spawn_backup_worker(
        source_root,
        source_root / "blobs",
        SOURCE,
        command.workflow_id,
        worker_id,
        barrier="intent_committed",
    )
    try:
        assert await wait_barrier(process, source_root) == command
        process.kill()
        await process.communicate()
        old = await release_dead_worker(factory, scenario, command, worker_id)
        await CompanyControls(factory).set_paused_registered(control(), identity(OWNER), True)
        before = await recovery_facts(factory, COMPANY, command.task_id, command.action_id)
        coordinator = backup_coordinator(backup_database, source_root, process)
        captured = await coordinator.capture(control(), identity(OWNER))
        restored = await coordinator.restore(control(), identity(OWNER), captured.envelope)
        assert restored.target_database == TARGET
        replay_started = monotonic()
        await target_replay(backup_database, tmp_path, source_root, command)
        replay_seconds = monotonic() - replay_started
        await assert_target_recovery(before, old, command)
        await coordinator.require_unchanged(
            restored.metadata.inventory, control(), identity(OWNER), restored.metadata.drain
        )
        save_drill_evidence(tmp_path, command, captured, restored, replay_seconds)
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()


def save_drill_evidence(
    root: Path,
    command: SegmentCommand,
    captured: SealedCapture,
    restored: RestoredCapture,
    replay_seconds: float,
) -> None:
    """Measured local timing follows successful conservation and source-unchanged checks."""
    completed_at = datetime.now(UTC)
    evidence = RecoveryDrillEvidence(
        source_database=SOURCE,
        target_database=TARGET,
        workflow_id=command.workflow_id,
        metadata_sha256=captured.metadata_sha256,
        captured_at=captured.captured_at,
        completed_at=completed_at,
        snapshot_age_seconds=(completed_at - captured.captured_at).total_seconds(),
        capture_seconds=captured.elapsed_seconds,
        data_restore_seconds=restored.elapsed_seconds,
        target_replay_seconds=replay_seconds,
        source_unchanged=True,
        old_fence_denied=True,
        no_reissue=True,
    )
    (root / "recovery-drill-evidence.json").write_text(evidence.model_dump_json())


async def source_dispatch(
    factory: async_sessionmaker[AsyncSession], source_root: Path
) -> tuple[GeneratedScenario, SegmentCommand]:
    """Public native author and owner-approved check populate the real portable dispatch."""
    scenario = await published_author(factory, source_root / "blobs")
    await scenario.execution.release(scenario.lease, identity(scenario.lease.actor_id))
    _, command = await prepare_check_dispatch(factory, scenario, reserve=False)
    save_process_config(source_root, scenario)
    await enqueue_check(factory, scenario, command)
    return scenario, command


async def release_dead_worker(
    factory: async_sessionmaker[AsyncSession],
    scenario: GeneratedScenario,
    command: SegmentCommand,
    worker_id: UUID,
) -> ExecutionLease:
    """Real clock expiry and normal reconciliation/release conserve the committed intent."""
    verifier = scenario.payload.children[1].binding
    for _ in range(32):
        async with factory() as clock:
            await clock.execute(
                text("SELECT set_config('nexus.company_id', :cid, true)"), {"cid": str(COMPANY)}
            )
            expired = await clock.scalar(
                text(
                    "SELECT lease_until <= clock_timestamp() FROM company_execution_work "
                    "WHERE task_id=:task"
                ),
                {"task": verifier.task_id},
            )
        if expired:
            break
        await asyncio.sleep(0.5)
    assert expired
    old = await scenario.execution.recover_dispatched(
        ledger(verifier), identity(verifier.actor_id), worker_id, command.segment_id
    )
    await scenario.execution.release(old, identity(verifier.actor_id))
    return old


def backup_coordinator(
    database: BackupDatabase, source_root: Path, process: asyncio.subprocess.Process
) -> OperatorBackupCoordinator:
    """Bind exact source namespace, actual waited process inventory and external key provider."""
    return OperatorBackupCoordinator(
        database.adapter,
        database.factory,
        {
            "fixture.blobs.v1": ProtectedBlobStore(
                source_root / "blobs", storage_symbol="fixture.blobs.v1"
            )
        },
        OwnedWorkerDrain(COMPANY, SOURCE, (process,)),
        EphemeralKey(),
    )


async def target_replay(
    database: BackupDatabase, tmp_path: Path, source_root: Path, command: SegmentCommand
) -> None:
    """Same config and workflow are replayed with a target-only runtime connection."""
    target_root = tmp_path / "target-worker"
    target_root.mkdir(mode=0o700)
    shutil.copy2(
        source_root / "native-process-config.json", target_root / "native-process-config.json"
    )
    result = await completed_native(
        await spawn_backup_worker(
            target_root,
            restored_namespace(database.adapter.config.restore_root, "fixture.blobs.v1"),
            TARGET,
            command.workflow_id,
            uuid4(),
        )
    )
    assert result.status == "outcome_unknown" and result.acceptance_id is None
    assert (target_root / "runtime-database.txt").read_text() == TARGET
    assert_no_issuance_phases(target_root)


async def assert_target_recovery(
    before: RecoveryFacts, old: ExecutionLease, command: SegmentCommand
) -> None:
    """Current target native writes preserve the old source intent and deny its prior fence."""
    engine = create_async_engine(local_url(TARGET, "nexus_company_app"))
    target = async_sessionmaker(engine, expire_on_commit=False)
    try:
        after = await recovery_facts(target, COMPANY, command.task_id, command.action_id)
        assert after.database == TARGET and before.database == SOURCE
        assert_unknown_conserved(before, after)
        with pytest.raises(ExecutionDeniedError):
            await ExecutionStore(target).release(old, identity(old.actor_id))
        unchanged = await recovery_facts(target, COMPANY, command.task_id, command.action_id)
        assert unchanged == after
    finally:
        await engine.dispose()
