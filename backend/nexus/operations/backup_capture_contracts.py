"""Authenticated descriptive capture metadata never supplies operator authority or target paths."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.management.base import SHA256, ValueContract
from nexus.operations.backup_drain import WorkerDrainWitness
from nexus.operations.backup_inventory import BackupInventory

METADATA_PATH = "operator-metadata/native-capture.json"
MAX_METADATA_BYTES = 4_194_304


class NativeCaptureMetadata(ValueContract):
    version: Literal["nexus.native.capture.v1"] = "nexus.native.capture.v1"
    scope: Literal["native-and-dbos.v1"] = "native-and-dbos.v1"
    company_id: UUID
    company_revision: str
    source_database: str
    database_sha256: SHA256
    inventory: BackupInventory
    drain: WorkerDrainWitness
    operation_id: UUID
    audit_trace_id: UUID

    @model_validator(mode="after")
    def exact_scope(self) -> "NativeCaptureMetadata":
        if (
            self.drain.company_id != self.company_id
            or self.drain.source_database != self.source_database
            or any(row.reference.company_id != self.company_id for row in self.inventory.artifacts)
            or not any(
                row.schema_name == "dbos" and row.table_name == "workflow_status"
                for row in self.inventory.tables
            )
        ):
            raise ValueError("Backup metadata company/source/DBOS scope differs")
        return self


class SealedCapture(ValueContract):
    envelope: bytes = Field(repr=False)
    metadata_sha256: SHA256
    captured_at: datetime
    elapsed_seconds: float = Field(ge=0)


class RestoredCapture(ValueContract):
    target_database: str
    metadata: NativeCaptureMetadata
    elapsed_seconds: float = Field(ge=0)


def metadata_bytes(value: NativeCaptureMetadata) -> bytes:
    raw = value.model_dump_json().encode()
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("Backup operator metadata exceeds its bound")
    return raw
