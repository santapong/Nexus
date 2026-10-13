"""Owner-scoped registered UTF8 ingestion; blobs/parse precede locked head publication."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.brain.blob_store import BrainBlobStore, validate_utf8
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_support import save_derivation, validate_derivation
from nexus.company.brain.event_store import append_event
from nexus.company.brain.ingestion_records import save_failure, save_parse, save_raw_records
from nexus.company.brain.ingestion_support import (
    prior_receipt,
    register_source,
    registered_source,
)
from nexus.company.brain.parser import ParsedSource, ParseRejectedError, parse_isolated
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)
from nexus.company.brain.source_models import (
    BrainSourceHead,
)
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    ArtifactRevisionRef,
    IngestCommand,
    IngestReceipt,
    ParseFailureRecord,
    SourceRecord,
    SourceRegistration,
    SourceRevisionRecord,
    SourceRevisionRef,
)


class PreparedIngest(ValueContract):
    source: SourceRevisionRecord
    artifact: ArtifactRevisionRecord
    policy: SourcePolicy
    parsed: ParsedSource | None
    failure: ParseFailureRecord | None
    derivation: DerivationRecord | None


def _recipe_identity(parser: str, chunker: str) -> str:
    """Length-bounded identifiers still need unambiguous pair identity."""
    return json.dumps((parser, chunker), separators=(",", ":"))


def _receipt(value: PreparedIngest) -> IngestReceipt:
    """Opaque references cannot accidentally retain a raw-text subclass in their Python object."""
    source, artifact = value.source, value.artifact
    return IngestReceipt(
        company_id=source.company_id,
        status="accepted" if value.parsed else "quarantined",
        source=SourceRevisionRef(
            company_id=source.company_id,
            source_id=source.source_id,
            source_revision_id=source.source_revision_id,
            revision=source.revision,
        ),
        artifact=ArtifactRevisionRef.model_validate(
            artifact.model_dump(include=set(ArtifactRevisionRef.model_fields))
        ),
        parser_version=value.policy.parser_version,
        chunker_version=value.policy.chunker_version,
        reason_code=value.failure.reason_code if value.failure else None,
    )


def _cas(head: BrainSourceHead | None, command: IngestCommand) -> None:
    current = head.current_revision_id if head is not None else None
    if current != command.expected_previous_revision_id:
        raise BrainConflictError("Current source head changed; reload before ingestion")


class BrainIngestionStore:
    """No implicit authority, extraction, URLs, paid work, completion or source content output."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        registry: SourceRegistry,
        blobs: BrainBlobStore,
    ) -> None:
        self._factory, self._registry, self._blobs = factory, registry, blobs

    async def register(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        registration: SourceRegistration,
        *,
        readers: tuple[UUID, ...],
    ) -> SourceRecord:
        if registration.company_id != scope.company_id:
            raise BrainDeniedError("Registered Brain source is unavailable")
        policy = self._registry.require_source(registration)
        async with brain_transaction(self._factory, scope, identity, owner=True) as (
            session,
            _,
            now,
        ):
            return await register_source(session, scope, registration, policy, readers, now)

    async def ingest(
        self, scope: BrainReadScope, identity: VerifiedIdentity, command: IngestCommand
    ) -> IngestReceipt:
        command = IngestCommand.model_validate(command.model_dump())
        if command.company_id != scope.company_id:
            raise BrainDeniedError("Registered Brain source is unavailable")
        async with brain_transaction(self._factory, scope, identity, owner=True) as (
            session,
            _,
            now,
        ):
            source, policy = await registered_source(
                session, scope, self._registry, command.source_id
            )
            self._recipe(command, policy)
            previous = await prior_receipt(session, scope, command)
            if previous is not None:
                return previous
            _cas(
                await session.get(
                    BrainSourceHead, {"company_id": scope.company_id, "source_id": source.source_id}
                ),
                command,
            )
        prepared = await self._prepare(scope, source, policy, command, now)
        async with brain_transaction(self._factory, scope, identity, owner=True) as (
            session,
            _,
            final_now,
        ):
            current, latest_policy = await registered_source(
                session, scope, self._registry, command.source_id
            )
            if current != source or latest_policy != policy:
                raise BrainConflictError("Registered source policy changed during parsing")
            previous = await prior_receipt(session, scope, command)
            if previous is not None:
                return previous
            head = await session.get(
                BrainSourceHead, {"company_id": scope.company_id, "source_id": source.source_id}
            )
            _cas(head, command)
            await _publish(session, scope, command, prepared, head, final_now)
            return _receipt(prepared)

    @staticmethod
    def _recipe(command: IngestCommand, policy: SourcePolicy) -> None:
        if (command.parser_version, command.chunker_version) != (
            policy.parser_version,
            policy.chunker_version,
        ):
            raise BrainDeniedError("Requested parser policy is unavailable")

    async def _prepare(
        self,
        scope: BrainReadScope,
        source: SourceRecord,
        policy: SourcePolicy,
        command: IngestCommand,
        now: datetime,
    ) -> PreparedIngest:
        snapshot = await self._registry.read(source, command.revision)
        text = validate_utf8(snapshot.raw_bytes, max_bytes=policy.max_bytes)
        artifact = ArtifactRevisionRecord.model_validate(
            command.artifact.model_dump()
            | {
                "resource": source.resource,
                "media_type": policy.media_type,
                "storage_symbol": self._blobs.storage_symbol,
                "raw_text": text,
                "recorded_at": now,
                "derivation_id": snapshot.derivation.derivation_id if snapshot.derivation else None,
            }
        )
        revision = SourceRevisionRecord(
            company_id=scope.company_id,
            source_id=source.source_id,
            source_revision_id=uuid5(source.source_id, f"source-revision-v1:{command.revision}"),
            revision=command.revision,
            artifact=command.artifact,
            source_event=snapshot.source_event,
            source_author=snapshot.source_author,
            ingested_at=now,
            recorded_by=scope.principal_id,
            derivation_id=snapshot.derivation.derivation_id if snapshot.derivation else None,
        )
        await self._blobs.save(command.artifact, snapshot.raw_bytes)
        try:
            parsed = await parse_isolated(revision, artifact, policy, sections=snapshot.sections)
        except ParseRejectedError as exc:
            failure = ParseFailureRecord.model_validate(
                {
                    "company_id": scope.company_id,
                    "failure_id": uuid5(
                        revision.source_revision_id,
                        "parse-failure:"
                        + _recipe_identity(policy.parser_version, policy.chunker_version),
                    ),
                    "source": revision,
                    "parser_version": policy.parser_version,
                    "chunker_version": policy.chunker_version,
                    "reason_code": exc.reason_code,
                    "recorded_at": now,
                }
            )
            return PreparedIngest(
                source=revision,
                artifact=artifact,
                policy=policy,
                parsed=None,
                failure=failure,
                derivation=snapshot.derivation,
            )
        return PreparedIngest(
            source=revision,
            artifact=artifact,
            policy=policy,
            parsed=parsed,
            failure=None,
            derivation=snapshot.derivation,
        )


async def _publish(
    session: AsyncSession,
    scope: BrainReadScope,
    command: IngestCommand,
    value: PreparedIngest,
    head: BrainSourceHead | None,
    now: datetime,
) -> None:
    """Short current-owner CAS publication contains only DB work, never blob/parse I/O."""
    source, artifact = value.source, value.artifact
    if value.derivation is not None:
        await validate_derivation(
            session,
            scope,
            value.derivation,
            command.artifact,
            artifact.resource.resource_id,
            value.policy,
            now,
        )
    await save_raw_records(session, artifact, source)
    if value.derivation is not None:
        await save_derivation(session, value.derivation)
    if value.parsed is not None:
        await save_parse(session, value.parsed, value.policy.search_config)
    elif value.failure is not None:
        await save_failure(session, value.failure)
    else:
        raise BrainConflictError("Source parse has no classified outcome")
    if head is None:
        head = BrainSourceHead(
            company_id=scope.company_id, source_id=source.source_id, generation=1
        )
        session.add(head)
    else:
        head.generation += 1
    head.current_revision_id, head.observed_at = source.source_revision_id, now
    head.fresh_until = (
        now + timedelta(seconds=value.policy.freshness_seconds)
        if value.policy.freshness_seconds
        else None
    )
    head.availability = "available" if value.parsed is not None else "quarantined"
    await session.flush()
    recipe_id = uuid5(
        source.source_revision_id, _recipe_identity(command.parser_version, command.chunker_version)
    )
    await append_event(
        session,
        scope,
        kind="source_revised",
        resource_id=artifact.resource.resource_id,
        deduplication_key=f"source:{source.source_revision_id}:{recipe_id}",
        now=now,
        source_revision_id=source.source_revision_id,
    )
