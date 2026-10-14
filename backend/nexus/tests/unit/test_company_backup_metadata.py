"""Authenticated metadata binds descriptive company/drain/database scope and exact inner bytes."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.operations.backup_capture_contracts import (
    METADATA_PATH,
    NativeCaptureMetadata,
    metadata_bytes,
)
from nexus.operations.backup_contracts import BackupArtifact
from nexus.operations.backup_drain import WorkerDrainWitness, WorkerExit
from nexus.operations.backup_inventory import BackupInventory, TableFingerprint
from nexus.operations.backup_package import pack_backup, unpack_backup
from nexus.operations.backup_restore import capture_metadata

COMPANY = UUID(int=1)
NOW = datetime.now(UTC)
DATABASE = b"PGDMP synthetic archive"


def metadata() -> NativeCaptureMetadata:
    """Typed synthetic metadata validates no actual database or authority."""
    return NativeCaptureMetadata(
        company_id=COMPANY,
        company_revision="company_015",
        source_database="assigned_source",
        database_sha256=hashlib.sha256(DATABASE).hexdigest(),
        inventory=BackupInventory(
            observed_at=NOW,
            artifacts=(),
            tables=(
                TableFingerprint(
                    schema_name="dbos",
                    table_name="workflow_status",
                    rows=1,
                    sha256="a" * 64,
                ),
            ),
        ),
        drain=WorkerDrainWitness(
            company_id=COMPANY,
            source_database="assigned_source",
            observed_at=NOW,
            workers=(WorkerExit(pid=123, exit_code=-9),),
        ),
        operation_id=UUID(int=9),
        audit_trace_id=UUID(int=10),
    )


@pytest.mark.parametrize(
    "field,value", [("company_id", UUID(int=2)), ("source_database", "foreign")]
)
def test_metadata_drain_cannot_substitute_company_or_database(field: str, value: object) -> None:
    original = metadata()
    changed = original.drain.model_copy(update={field: value})
    with pytest.raises(ValueError, match="scope differs"):
        NativeCaptureMetadata.model_validate({**original.model_dump(), "drain": changed})


def test_metadata_requires_actual_dbos_workflow_table_name() -> None:
    original = metadata()
    wrong = original.inventory.model_copy(
        update={
            "tables": (
                TableFingerprint(
                    schema_name="public",
                    table_name="company_work",
                    rows=1,
                    sha256="a" * 64,
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="scope differs"):
        NativeCaptureMetadata.model_validate({**original.model_dump(), "inventory": wrong})


@pytest.mark.parametrize("extra", [False, True])
def test_exact_inner_artifacts_and_database_are_bound(extra: bool) -> None:
    original = metadata()
    artifacts: tuple[BackupArtifact, ...] = (
        BackupArtifact(relative_path=METADATA_PATH, data=metadata_bytes(original)),
    )
    if extra:
        artifacts += (BackupArtifact(relative_path="unregistered.blob", data=b"extra"),)
    packed = pack_backup(COMPANY, "company_015", NOW, DATABASE, artifacts)
    contents = unpack_backup(packed)
    if extra:
        with pytest.raises(ValueError, match="namespaces differ"):
            capture_metadata(contents)
    else:
        assert capture_metadata(contents) == original


def test_authenticated_outer_hash_does_not_replace_metadata_dump_hash() -> None:
    changed = metadata().model_copy(update={"database_sha256": "b" * 64})
    packed = pack_backup(
        COMPANY,
        "company_015",
        NOW,
        DATABASE,
        (BackupArtifact(relative_path=METADATA_PATH, data=metadata_bytes(changed)),),
    )
    with pytest.raises(ValueError, match="dump differs"):
        capture_metadata(unpack_backup(packed))
