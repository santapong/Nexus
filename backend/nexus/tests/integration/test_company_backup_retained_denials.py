"""Read-only boundary matrix against the preserved successful drill; never reset/migrate its DBs."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.operations.backup_artifacts import collect_artifacts
from nexus.operations.backup_capture import OperatorBackupCoordinator
from nexus.operations.backup_capture_contracts import NativeCaptureMetadata
from nexus.operations.backup_config import LocalPostgresBackupConfig
from nexus.operations.backup_drain import WorkerDrainWitness, WorkerExit
from nexus.operations.backup_postgres import PostgresBackupAdapter, require_empty_target
from nexus.tests.backup_postgres_fixture import SOCKET, SOURCE, TARGET, local_url
from nexus.tests.integration.test_company_backup_postgres_drill import EphemeralKey
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity

PRESERVED = Path(
    "/home/santapong/.codex/nexus-local-release-fixtures-20261014-continued/"
    "backup-matching-drill-1/preserved-run"
)


def retained_metadata() -> NativeCaptureMetadata:
    """Prerequisite is the already preserved real drill; absence skips without fabricating it."""
    path = PRESERVED / "restore/artifacts/operator-metadata/native-capture.json"
    if not path.is_file():
        pytest.skip("retained actual matching drill is unavailable")
    return NativeCaptureMetadata.model_validate_json(path.read_bytes())


class FixedDrain:
    """Comparison-only controlled dependency; never substitutes for original actual worker proof."""

    def __init__(self, witness: WorkerDrainWitness) -> None:
        self.witness = witness

    async def observe(self, company_id: UUID) -> WorkerDrainWitness:
        """Return the selected comparison witness; coordinator must reject inconsistent scope."""
        return self.witness


def adapter() -> PostgresBackupAdapter:
    """Only the exact retained source/target pair is available to this test adapter."""
    return PostgresBackupAdapter(
        LocalPostgresBackupConfig(
            enabled=True,
            company_id=COMPANY,
            socket=Path(SOCKET),
            port=55438,
            admin_user="santapong",
            source_database=SOURCE,
            target_database=TARGET,
            restore_root=PRESERVED / "new-unused-restore",
        )
    )


@pytest.mark.parametrize("change", ["company", "source", "process", "exit"])
async def test_second_drain_inventory_substitution_is_denied(change: str) -> None:
    metadata = retained_metadata()
    old = metadata.drain
    changed = old.model_copy(
        update={
            "company_id": UUID(int=2) if change == "company" else COMPANY,
            "source_database": "foreign" if change == "source" else SOURCE,
            "workers": (
                WorkerExit(
                    pid=old.workers[0].pid + (1 if change == "process" else 0),
                    exit_code=0 if change == "exit" else old.workers[0].exit_code,
                ),
            ),
        }
    )
    engine = create_async_engine(local_url(SOURCE, "nexus_company_app"))
    try:
        coordinator = OperatorBackupCoordinator(
            adapter(),
            async_sessionmaker(engine, expire_on_commit=False),
            {},
            FixedDrain(changed),
            EphemeralKey(),
        )
        with pytest.raises(ValueError, match="drain inventory changed"):
            await coordinator.require_unchanged(metadata.inventory, control(), identity(OWNER), old)
    finally:
        await engine.dispose()


async def test_nonowner_cannot_qualify_retained_capture() -> None:
    metadata = retained_metadata()
    engine = create_async_engine(local_url(SOURCE, "nexus_company_app"))
    try:
        coordinator = OperatorBackupCoordinator(
            adapter(),
            async_sessionmaker(engine, expire_on_commit=False),
            {},
            FixedDrain(metadata.drain),
            EphemeralKey(),
        )
        with pytest.raises(ValueError):
            await coordinator.require_unchanged(
                metadata.inventory, control(ACTOR), identity(ACTOR), metadata.drain
            )
    finally:
        await engine.dispose()


async def test_nonempty_retained_target_cannot_be_restored_again() -> None:
    retained_metadata()
    value = adapter()
    async with value.connection(target=True) as connection:
        with pytest.raises(ValueError, match="not empty"):
            await require_empty_target(connection)
    with pytest.raises(ValueError, match="not empty"):
        await value.restore(b"PGDMP synthetic cannot reach restore process")


async def test_missing_registered_namespace_and_total_byte_limit_are_denied() -> None:
    metadata = retained_metadata()
    with pytest.raises(ValueError, match="namespace is unavailable"):
        await collect_artifacts(metadata.inventory.artifacts, {}, limit=268435456)
    readers = {
        "fixture.blobs.v1": ProtectedBlobStore(
            PRESERVED / "source-worker/blobs", storage_symbol="fixture.blobs.v1"
        )
    }
    assert len(await collect_artifacts(metadata.inventory.artifacts, readers, limit=268435456)) == 2
    with pytest.raises(ValueError, match="bytes differ"):
        await collect_artifacts(metadata.inventory.artifacts, readers, limit=1)
