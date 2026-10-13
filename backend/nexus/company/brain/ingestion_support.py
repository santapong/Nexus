"""Locked source registration, immutable provenance mappings and parsed row persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_models import BrainAccessEvent, BrainResource, BrainResourceAccess
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.evidence_models import (
    BrainParseFailure,
    BrainParseRevision,
)
from nexus.company.brain.ingestion_records import artifact_record, revision_record, source_record
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceRevision,
)
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    IngestCommand,
    IngestReceipt,
    SourceRecord,
    SourceRegistration,
    SourceRevisionRef,
)
from nexus.company.directory_models import DirectoryMembership


async def registered_source(
    session: AsyncSession, scope: BrainReadScope, registry: SourceRegistry, source_id: UUID
) -> tuple[SourceRecord, SourcePolicy]:
    row = await session.get(BrainSource, {"company_id": scope.company_id, "source_id": source_id})
    if row is None:
        raise BrainDeniedError("Registered Brain source is unavailable")
    record = source_record(row)
    policy = registry.require_source(record)
    resource = await session.get(
        BrainResource, {"company_id": scope.company_id, "resource_id": row.resource_id}
    )
    if (
        resource is None
        or not resource.active
        or (record.authority_profile, record.data_classification)
        != (policy.authority_profile, policy.data_classification)
    ):
        raise BrainDeniedError("Current registered source policy is unavailable")
    return record, policy


async def register_source(
    session: AsyncSession,
    scope: BrainReadScope,
    registration: SourceRegistration,
    policy: SourcePolicy,
    readers: tuple[UUID, ...],
    now: datetime,
) -> SourceRecord:
    existing = await session.get(
        BrainSource, {"company_id": scope.company_id, "source_id": registration.source_id}
    )
    if existing is not None:
        record = source_record(existing)
        if (
            record.resource,
            record.source_symbol,
            record.external_key,
            record.authority_profile,
            record.data_classification,
        ) != (
            registration.resource,
            registration.source_symbol,
            registration.external_key,
            policy.authority_profile,
            policy.data_classification,
        ):
            raise BrainConflictError("Registered source identity/policy is immutable")
        return record  # Replays never restore or widen any current resource grant.
    await _initial_resource(session, scope, registration, readers, now)
    row = BrainSource(
        company_id=scope.company_id,
        source_id=registration.source_id,
        resource_id=registration.resource.resource_id,
        source_symbol=registration.source_symbol,
        external_key=registration.external_key,
        authority_profile=policy.authority_profile,
        data_classification=policy.data_classification,
        recorded_by=scope.principal_id,
        recorded_at=now,
    )
    session.add(row)
    await session.flush()
    return source_record(row)


async def _initial_resource(
    session: AsyncSession,
    scope: BrainReadScope,
    registration: SourceRegistration,
    readers: tuple[UUID, ...],
    now: datetime,
) -> None:
    if not 1 <= len(readers) <= 32 or len(set(readers)) != len(readers):
        raise BrainDeniedError("Explicit initial source readership is unavailable")
    for principal in readers:
        member = await session.get(DirectoryMembership, (scope.company_id, principal))
        if member is None or not member.principal_active or not member.membership_active:
            raise BrainDeniedError("Initial source reader is unavailable")
    resource_id = registration.resource.resource_id
    if (
        await session.get(
            BrainResource, {"company_id": scope.company_id, "resource_id": resource_id}
        )
        is not None
    ):
        raise BrainConflictError("New source registration requires its own registered resource")
    session.add(
        BrainResource(
            company_id=scope.company_id,
            resource_id=resource_id,
            kind="source",
            active=True,
            acl_generation=1,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    for principal in readers:
        session.add(
            BrainResourceAccess(
                company_id=scope.company_id,
                resource_id=resource_id,
                principal_id=principal,
                active=True,
                generation=1,
                expires_at=None,
            )
        )
        session.add(
            BrainAccessEvent(
                company_id=scope.company_id,
                event_id=uuid5(resource_id, f"initial-reader:{principal}"),
                resource_id=resource_id,
                principal_id=principal,
                generation=1,
                active=True,
                expires_at=None,
                owner_id=scope.principal_id,
                operation_id=scope.operation_id,
                trace_id=scope.trace_id,
                recorded_at=now,
            )
        )
    await session.flush()
    await append_event(
        session,
        scope,
        kind="acl_changed",
        resource_id=resource_id,
        deduplication_key=f"acl:{resource_id}:1",
        now=now,
        resource_generation=1,
    )


async def prior_receipt(
    session: AsyncSession, scope: BrainReadScope, command: IngestCommand
) -> IngestReceipt | None:
    row = await session.scalar(
        select(BrainSourceRevision).where(
            BrainSourceRevision.company_id == scope.company_id,
            BrainSourceRevision.source_id == command.source_id,
            BrainSourceRevision.revision == command.revision,
        )
    )
    if row is None:
        return None
    artifact = await session.get(
        BrainArtifactRevision, (scope.company_id, row.artifact_revision_id)
    )
    if artifact is None:
        raise BrainDeniedError("Original source artifact is unavailable")
    record = artifact_record(artifact)
    source = revision_record(row, record)
    source_ref = SourceRevisionRef(
        company_id=source.company_id,
        source_id=source.source_id,
        source_revision_id=source.source_revision_id,
        revision=source.revision,
    )
    artifact_ref = ArtifactRevisionRef.model_validate(
        record.model_dump(include=set(ArtifactRevisionRef.model_fields))
    )
    if (
        record.artifact_id,
        record.artifact_revision_id,
        record.revision,
        record.sha256,
        record.byte_length,
    ) != (
        command.artifact.artifact_id,
        command.artifact.artifact_revision_id,
        command.artifact.revision,
        command.artifact.sha256,
        command.artifact.byte_length,
    ):
        return IngestReceipt(
            company_id=scope.company_id,
            status="conflict",
            source=source_ref,
            artifact=artifact_ref,
            parser_version=command.parser_version,
            chunker_version=command.chunker_version,
            reason_code="revision_bytes_conflict",
        )
    recipe = (
        BrainParseRevision.company_id == scope.company_id,
        BrainParseRevision.source_revision_id == row.source_revision_id,
        BrainParseRevision.parser_version == command.parser_version,
        BrainParseRevision.chunker_version == command.chunker_version,
    )
    success = await session.scalar(select(BrainParseRevision).where(*recipe))
    failed = await session.scalar(
        select(BrainParseFailure).where(
            BrainParseFailure.company_id == scope.company_id,
            BrainParseFailure.source_revision_id == row.source_revision_id,
            BrainParseFailure.parser_version == command.parser_version,
            BrainParseFailure.chunker_version == command.chunker_version,
        )
    )
    if success is not None and failed is not None:
        raise BrainConflictError("Source parse recipe has incompatible persisted outcomes")
    if success is None and failed is None:
        return None
    return IngestReceipt(
        company_id=scope.company_id,
        status="accepted" if success else "quarantined",
        source=source_ref,
        artifact=artifact_ref,
        parser_version=command.parser_version,
        chunker_version=command.chunker_version,
        reason_code=failed.reason_code if failed else None,
    )
