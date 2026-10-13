"""Typed claim publication; model output stays proposed and owner reports stay sourced."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.claim_links import claim_record, publish_link
from nexus.company.brain.claim_models import BrainClaimEvidence, BrainClaimHead, BrainClaimRevision
from nexus.company.brain.claims import ClaimLink, ClaimRecord
from nexus.company.brain.event_store import append_event
from nexus.company.brain.publication_contracts import (
    ClaimLinkPublication,
    ClaimPublication,
    ClaimPublicationBatch,
)
from nexus.company.brain.publication_evidence import (
    prepare_evidence,
    recheck_publication,
    require_mutation,
    require_source_report,
)
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)


class BrainClaimStore:
    """Internal source/proposal store; no verified outcome, mutation of allowance or HTTP write."""

    def __init__(
        self, factory: async_sessionmaker[AsyncSession], retriever: PersistentBrainRetriever
    ) -> None:
        self.factory, self.retriever = factory, retriever

    async def publish_manual(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: ClaimPublication,
        *,
        source_report: bool = False,
    ) -> ClaimRecord:
        command = ClaimPublication.model_validate_json(command.model_dump_json())
        require_source_report(source_report, command.draft.evidence)
        return (
            await self._publish(
                scope,
                identity,
                (command,),
                model=False,
                source_report=source_report,
                recipe="owner-claim-v1",
            )
        )[0]

    async def propose_batch(
        self, scope: BrainReadScope, identity: VerifiedIdentity, batch: ClaimPublicationBatch
    ) -> tuple[ClaimRecord, ...]:
        batch = ClaimPublicationBatch.model_validate_json(batch.model_dump_json())
        if batch.company_id != scope.company_id:
            raise BrainDeniedError("Claim proposal is unavailable")
        return await self._publish(
            scope,
            identity,
            batch.claims,
            model=True,
            source_report=False,
            recipe=batch.extraction_version,
        )

    async def link(
        self, scope: BrainReadScope, identity: VerifiedIdentity, command: ClaimLinkPublication
    ) -> ClaimLink:
        return await publish_link(self.factory, self.retriever, scope, identity, command)

    async def _publish(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        commands: tuple[ClaimPublication, ...],
        *,
        model: bool,
        source_report: bool,
        recipe: str,
    ) -> tuple[ClaimRecord, ...]:
        if any(command.company_id != scope.company_id for command in commands):
            raise BrainDeniedError("Claim publication is unavailable")
        resources = tuple(sorted({command.resource.resource_id for command in commands}))
        async with brain_transaction(self.factory, scope, identity, owner=not model) as (
            session,
            control,
            _,
        ):
            await require_mutation(session, control, scope, identity, model=model)
        references = tuple(
            sorted(
                {
                    ref
                    for command in commands
                    for ref in command.draft.evidence + command.challenging
                },
                key=lambda row: row.evidence_id,
            )
        )
        prepared = await prepare_evidence(self.retriever, scope, identity, references)
        async with brain_transaction(self.factory, scope, identity, owner=not model) as (
            session,
            control,
            _,
        ):
            now = await recheck_publication(
                self.retriever, session, control, scope, identity, prepared, resources, model=model
            )
            records = tuple(
                [
                    await _publish_claim(
                        session,
                        command,
                        now,
                        model=model,
                        source_report=source_report,
                        recipe=recipe,
                    )
                    for command in commands
                ]
            )
            for record in records:
                await append_event(
                    session,
                    scope,
                    kind="claims_changed",
                    resource_id=record.resource.resource_id,
                    deduplication_key=f"claim:{record.claim_revision_id}",
                    now=record.ingested_at,
                )
            await recheck_publication(
                self.retriever, session, control, scope, identity, prepared, resources, model=model
            )
            return records


async def _publish_claim(
    session: AsyncSession,
    command: ClaimPublication,
    now: datetime,
    *,
    model: bool,
    source_report: bool,
    recipe: str,
) -> ClaimRecord:
    origin: Literal["model", "source", "operator"] = (
        "model" if model else "source" if source_report else "operator"
    )
    status: Literal["proposed", "source_report"] = "source_report" if source_report else "proposed"
    draft = command.draft
    revision_id = uuid5(
        command.company_id,
        json.dumps(
            ("claim", str(draft.claim_id), command.revision, recipe, origin), separators=(",", ":")
        ),
    )
    value = ClaimRecord(
        company_id=command.company_id,
        claim_id=draft.claim_id,
        claim_revision_id=revision_id,
        revision=command.revision,
        resource=command.resource,
        kind=draft.kind,
        text=draft.text,
        supporting=tuple(sorted(draft.evidence, key=lambda ref: ref.evidence_id)),
        challenging=tuple(sorted(command.challenging, key=lambda ref: ref.evidence_id)),
        source_event=draft.source_event,
        ingested_at=now,
        validity=draft.validity,
        origin=origin,
        status=status,
    )
    previous = await session.scalar(
        select(BrainClaimRevision).where(
            BrainClaimRevision.company_id == command.company_id,
            BrainClaimRevision.claim_id == draft.claim_id,
            BrainClaimRevision.revision == command.revision,
        )
    )
    if previous is not None:
        record = await claim_record(session, previous)
        if record.model_dump(exclude={"ingested_at"}) != value.model_dump(exclude={"ingested_at"}):
            raise BrainConflictError("Claim revision identity cannot be rebound")
        return record
    head = await session.get(BrainClaimHead, (command.company_id, draft.claim_id))
    current = head.current_revision_id if head is not None else None
    if current != command.expected_previous_revision_id:
        raise BrainConflictError("Current claim head changed; reload before publication")
    if head is not None:
        prior = await session.get(
            BrainClaimRevision, (command.company_id, head.current_revision_id)
        )
        if prior is None or prior.resource_id != command.resource.resource_id:
            raise BrainConflictError("Logical claim resource cannot be rebound")
    await _save_claim(session, value)
    if head is None:
        session.add(
            BrainClaimHead(
                company_id=value.company_id,
                claim_id=value.claim_id,
                current_revision_id=value.claim_revision_id,
            )
        )
    else:
        head.current_revision_id = value.claim_revision_id
    await session.flush()
    return value


async def _save_claim(session: AsyncSession, value: ClaimRecord) -> None:
    session.add(
        BrainClaimRevision(
            company_id=value.company_id,
            claim_id=value.claim_id,
            claim_revision_id=value.claim_revision_id,
            resource_id=value.resource.resource_id,
            revision=value.revision,
            kind=value.kind,
            text=value.text,
            source_event_json=value.source_event.model_dump_json(),
            ingested_at=value.ingested_at,
            validity_start=value.validity.start,
            validity_end=value.validity.end,
            origin=value.origin,
            status=value.status,
            verification_id=None,
            receipt_id=None,
        )
    )
    await session.flush()
    for relationship, refs in (("supports", value.supporting), ("challenges", value.challenging)):
        for ref in refs:
            session.add(
                BrainClaimEvidence(
                    company_id=value.company_id,
                    claim_revision_id=value.claim_revision_id,
                    evidence_id=ref.evidence_id,
                    relationship=relationship,
                )
            )
    await session.flush()
