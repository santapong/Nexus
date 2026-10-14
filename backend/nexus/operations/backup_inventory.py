"""Exact native/database snapshot hashes and immutable artifact references; no body rendering."""

import hashlib
import re
import struct
from datetime import datetime
from uuid import UUID

from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.base import SHA256, ValueContract


class TableFingerprint(ValueContract):
    schema_name: str
    table_name: str
    rows: int = Field(ge=0)
    sha256: SHA256


class ArtifactLocation(ValueContract):
    storage_symbol: str
    reference: ArtifactRevisionRef
    declared_classification: str | None


class BackupInventory(ValueContract):
    observed_at: datetime
    tables: tuple[TableFingerprint, ...] = Field(min_length=1, max_length=1000)
    artifacts: tuple[ArtifactLocation, ...] = Field(max_length=10000)


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("Backup native object name is unavailable")
    return '"' + value + '"'


async def table_fingerprint(
    connection: AsyncConnection, schema: str, table: str
) -> TableFingerprint:
    digest, count, total = hashlib.sha256(), 0, 0
    query = (
        f"SELECT row_to_json(t)::text AS row FROM {identifier(schema)}.{identifier(table)} t "
        'ORDER BY row_to_json(t)::text COLLATE "C"'
    )
    stream = await connection.stream_scalars(text(query))
    async for value in stream:
        raw = str(value).encode()
        count, total = count + 1, total + len(raw)
        if count > 1_000_000 or total > 268_435_456:
            raise ValueError("Backup native row inventory exceeds its bound")
        digest.update(struct.pack(">Q", len(raw)))
        digest.update(raw)
    return TableFingerprint(
        schema_name=schema, table_name=table, rows=count, sha256=digest.hexdigest()
    )


async def native_inventory(connection: AsyncConnection, company_id: UUID) -> BackupInventory:
    names = await table_names(connection)
    tables = []
    for schema, table in names:
        if schema == "public" and not table.startswith("company_"):
            raise ValueError("Backup foreign public objects are unavailable")
        tables.append(await table_fingerprint(connection, schema, table))
    return BackupInventory(
        observed_at=await connection.scalar(text("SELECT clock_timestamp()")),
        tables=tuple(tables),
        artifacts=await artifact_locations(connection, company_id),
    )


async def table_names(connection: AsyncConnection) -> tuple[tuple[str, str], ...]:
    names = (
        (
            await connection.execute(
                text(
                    "SELECT n.nspname,c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname IN ('public','dbos') AND c.relkind IN ('r','p') "
                    "ORDER BY n.nspname,c.relname"
                )
            )
        )
        .mappings()
        .all()
    )
    if not names or len(names) > 1000:
        raise ValueError("Backup native object inventory is unavailable")
    return tuple((row["nspname"], row["relname"]) for row in names)


async def artifact_locations(
    connection: AsyncConnection, company_id: UUID
) -> tuple[ArtifactLocation, ...]:
    records = (
        (
            await connection.execute(
                text(
                    "SELECT artifact_id,artifact_revision_id,revision,sha256,byte_length,"
                    "storage_symbol,"
                    "data_classification FROM company_brain_artifact_revisions "
                    "WHERE company_id=:company ORDER BY artifact_revision_id"
                ),
                {"company": company_id},
            )
        )
        .mappings()
        .all()
    )
    if len(records) > 10000:
        raise ValueError("Backup artifact inventory exceeds its bound")
    return tuple(
        ArtifactLocation(
            storage_symbol=row["storage_symbol"],
            declared_classification=row["data_classification"],
            reference=ArtifactRevisionRef(
                company_id=company_id,
                artifact_id=row["artifact_id"],
                artifact_revision_id=row["artifact_revision_id"],
                revision=row["revision"],
                sha256=row["sha256"],
                byte_length=row["byte_length"],
            ),
        )
        for row in records
    )
