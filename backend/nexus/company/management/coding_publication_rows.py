"""Actual native/model joins and immutable paired Brain rows; none accepts posted provenance.

Cohesion exception: one complete native/protected result join and its atomic
two-source append/replay preserve all immutable source/parse/privacy edges here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contracts import BuilderArtifact
from nexus.builder.patch_text import apply_text
from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import (
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
)
from nexus.company.brain.ingestion_records import artifact_record, revision_record
from nexus.company.brain.ingestion_store import PreparedIngest, _publish
from nexus.company.brain.parser import parse_identity
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    ArtifactRevisionRef,
    EvidenceRef,
    IngestCommand,
    IngestReceipt,
    SourceRegistration,
    SourceRevisionRecord,
    SourceRevisionRef,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import CodeChangeContent, validate_code_change
from nexus.company.management.coding_intent import require_coding_registry
from nexus.company.management.coding_prepared_contracts import StoredCodingRequest
from nexus.company.management.coding_publication_contracts import (
    RECIPE,
    CodingModelOrigin,
    CodingPublicationRules,
    PublicationKind,
    PublishedCodingPatch,
    publication_identity,
)
from nexus.company.management.coding_sources import require_coding_sources
from nexus.company.management.cycle_cost_contracts import NativeCostSelection
from nexus.company.management.cycle_model_facts import join_cycle_model_fact
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_budget import billing_day
from nexus.harness.lifecycle import ActionState
from nexus.harness.model_evidence import ModelEvidence


@dataclass(frozen=True, slots=True)
class PublicationPair:
    origin: PreparedIngest
    patch: PreparedIngest
    value: PublishedCodingPatch
    inputs: tuple[ArtifactRevisionRef, ...]
    resources: tuple[UUID, ...]


def require_native_result(loaded: StoredCodingRequest, native: NativeCostSelection) -> None:
    """Complete immutable native join BEFORE model bytes; no supplied DTO grants this read.

    Cohesion exception: identity/approval/receipt/attempt/day/hold checks form one join.
    """
    header = loaded.header
    action, work, intent, hold, attempt = (
        native.action,
        native.directory.work,
        native.intent,
        native.hold,
        native.attempt,
    )
    if (
        work is None
        or intent is None
        or intent.receipt is None
        or hold is None
        or attempt is None
        or len(intent.receipt.artifacts) != 1
    ):
        raise ValueError("Coding publication native result is incomplete")
    receipt, approval = intent.receipt, action.approval
    artifact = receipt.artifacts[0]
    expected = (header.company_id, header.task_id, header.trace_id, header.action_id)
    if (
        (
            action.company_id,
            action.proposal.task_id,
            action.proposal.trace_id,
            action.proposal.action_id,
        )
        != expected
        or (intent.company_id, intent.task_id, intent.trace_id, intent.action_id) != expected
        or intent.run_id != header.run_id
        or intent.proposal_hash != action.proposal_hash
        or intent.state != "succeeded"
        or intent.attempt_kind != "model_requests"
        or registration_digest(work.registration) != header.registration_sha256
        or (
            native.directory.company_id,
            native.directory.task_id,
            native.directory.trace_id,
            native.directory.actor_id,
            native.directory.workspace_id,
            native.directory.root_task_id,
        )
        != (
            header.company_id,
            header.task_id,
            header.trace_id,
            header.actor_id,
            header.workspace_id,
            header.root_task_id,
        )
        or (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.fence,
            attempt.kind,
            attempt.reserved_at,
        )
        != (*expected, intent.intent_fence, "model_requests", intent.created_at)
        or (
            receipt.company_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.action_id,
            receipt.proposal_hash,
            receipt.outcome,
            receipt.receipt_id,
        )
        != (
            *expected,
            action.proposal_hash,
            "succeeded",
            uuid5(header.action_id, "model-receipt-v1"),
        )
        or (
            artifact.company_id,
            artifact.artifact_id,
            artifact.revision,
            artifact.allowed_principals,
        )
        != (
            header.company_id,
            uuid5(header.action_id, str(header.parameters.request_id)),
            "model-result-envelope-v1",
            (header.actor_id, header.owner_id),
        )
        or (hold.company_id, hold.task_id, hold.action_id, hold.day, hold.amount_usd, hold.state)
        != (
            header.company_id,
            header.task_id,
            header.action_id,
            billing_day(intent.created_at),
            action.proposal.estimated_cost_usd,
            "reconciled",
        )
        or hold.actual_usd is None
        or action.state != ActionState.AUTHORIZED
        or action.consumed_at is None
        or approval is None
        or approval.decision != "approved"
        or (
            approval.company_id,
            approval.action_id,
            approval.action_revision,
            approval.action_hash,
            approval.approver_id,
        )
        != (
            header.company_id,
            header.action_id,
            action.proposal.revision,
            action.proposal_hash,
            header.owner_id,
        )
        or not approval.issued_at <= action.consumed_at <= intent.created_at < approval.expires_at
    ):
        raise ValueError("Coding native result/protected recipient binding differs")


def model_origin(
    loaded: StoredCodingRequest,
    native: NativeCostSelection,
    saved: ModelEvidence,
    registry: ModelRegistry,
    *,
    wire: bytes,
) -> CodingModelOrigin:
    """Pure complete join after actual owner/native/source admission and protected file read."""
    prepared = loaded.prepared
    saved = ModelEvidence.model_validate_json(saved.model_dump_json(by_alias=True))
    saved.require_binding()
    work, intent, hold = native.directory.work, native.intent, native.hold
    if (
        work is None
        or intent is None
        or intent.receipt is None
        or hold is None
        or len(intent.receipt.artifacts) != 1
    ):
        raise ValueError("Coding result has no exact native receipt/charge")
    receipt = intent.receipt
    selected = require_coding_registry(prepared, registry)
    fact = join_cycle_model_fact(
        native.directory.directory_data(),
        work,
        native.action,
        prepared.request,
        prepared.input_recipe,
        registry,
        attempt=native.attempt.native_data() if native.attempt else None,
        intent=intent,
        hold=hold.native_data(),
        artifact=receipt.artifacts[0],
        evidence=saved,
        wire=wire,
    )
    if fact.billing != "known":
        error = ValueError("Coding publication protected native cost is unconfirmed")
        error.__dict__["_nexus_coding_publication_blockers"] = fact.blockers
        raise error
    if (
        intent.state != "succeeded"
        or saved.result.status != "response"
        or saved.result.billing != "known"
        or saved.result.usage is None
        or saved.result.structured_json is None
        or saved.result.tool_calls
        or saved.request != prepared.request
        or saved.input_estimate != prepared.input_estimate
        or saved.recipe != prepared.input_recipe
        or saved.model != selected
        or saved.owner_id != loaded.header.owner_id
        or saved.model.price is None
        or native.action.proposal_hash != saved.action_hash
        or hold.actual_usd is None
    ):
        raise ValueError("Coding publication needs its exact known successful protected result")
    schema = prepared.request.output_schema
    assert schema is not None
    content = CodeChangeContent.model_validate_json(
        schema.validate_output(saved.result.structured_json)
    )
    originals = require_coding_sources(prepared.binding, prepared.context, prepared.sources)
    changes = validate_code_change(
        content, prepared.binding, manifest=prepared.context.manifest, originals=originals
    )
    updated = []
    for change in changes:
        raw = apply_text(originals[change.path], change)
        updated.append(
            BuilderArtifact(
                path=change.path, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw)
            )
        )
    return CodingModelOrigin(
        header=loaded.header,
        native_proposal_sha256=native.action.proposal_hash,
        intent_fence=intent.intent_fence,
        intent_created_at=intent.created_at,
        receipt_id=receipt.receipt_id,
        receipt_sha256=canonical_sha256(receipt),
        model_artifact_id=receipt.artifacts[0].artifact_id,
        model_artifact_sha256=receipt.artifacts[0].sha256,
        result_sha256=canonical_sha256(saved.result),
        provider=saved.model.provider,
        api_family=saved.model.api_family,
        model_id=saved.model.model_id,
        price=saved.model.price,
        usage=saved.result.usage,
        actual_usd=hold.actual_usd,
        day=hold.day,
        source_event_at=saved.source_event_at,
        checked_at=saved.checked_at,
        content=content,
        content_sha256=canonical_sha256(content),
        changed_files=tuple(updated),
    )


def prepare_pair(
    origin: CodingModelOrigin,
    rules: CodingPublicationRules,
    storage_symbol: str,
    now: datetime,
    inputs: tuple[ArtifactRevisionRef, ...],
) -> PublicationPair:
    """Real bounded identity parsing/application; thread owner stays with the calling store.

    Cohesion exception: both source/derivation records use one exact original result.
    """
    origin = CodingModelOrigin.model_validate_json(origin.model_dump_json(by_alias=True))
    rules = CodingPublicationRules.model_validate_json(rules.model_dump_json())
    header = origin.header
    raw = (origin.model_dump_json(by_alias=True) + "\n").encode()
    values: list[PreparedIngest] = []
    resources = tuple(row.resource_id for row in header.contributors)
    cases: tuple[tuple[PublicationKind, SourceRegistration, SourcePolicy, bytes], ...] = (
        ("model_origin", rules.origin, rules.origin_policy, raw),
        ("code_patch", rules.patch, rules.patch_policy, origin.content.patch.encode("utf-8")),
    )
    for kind, registration, policy, body in cases:
        source, artifact, derivation_id = publication_identity(
            header.company_id, header.action_id, header.request_sha256, kind, body
        )
        if (rules.company_id, rules.action_id, registration.source_id) != (
            header.company_id,
            header.action_id,
            source.source_id,
        ):
            raise ValueError("Coding output differs from its exact configured source")
        contributors = (
            tuple(row.current for row in header.source_heads)
            if not values
            else (
                SourceRevisionRef(
                    **values[0].source.model_dump(include=set(SourceRevisionRef.model_fields))
                ),
            )
        )
        derivation = DerivationRecord(
            company_id=header.company_id,
            derivation_id=derivation_id,
            artifact=artifact,
            recipe_version=RECIPE,
            kind=kind,
            contributors=contributors,
            evidence=tuple(
                EvidenceRef(company_id=header.company_id, evidence_id=key)
                for key in origin.content.evidence_ids
            )
            if not values
            else (),
            model_recipe=header.parameters.input_recipe_id,
            recorded_at=origin.checked_at,
        )
        record = ArtifactRevisionRecord(
            **artifact.model_dump(),
            resource=registration.resource,
            media_type=policy.media_type,
            storage_symbol=storage_symbol,
            raw_text=body.decode(),
            recorded_at=origin.checked_at,
            derivation_id=derivation_id,
        )
        source_record = SourceRevisionRecord(
            **source.model_dump(),
            artifact=artifact,
            source_event=SourceTime(
                precision="instant",
                value=origin.checked_at.isoformat(),
                basis="native model result recorded",
            ),
            ingested_at=now,
            recorded_by=header.owner_id,
            source_author=str(header.actor_id),
            derivation_id=derivation_id,
        )
        parsed = parse_identity(source_record, record, policy)
        values.append(
            PreparedIngest(
                source=source_record,
                artifact=record,
                policy=policy,
                parsed=parsed,
                failure=None,
                derivation=derivation,
            )
        )
    first, last = values
    # Explicit base projections avoid retaining private/raw record subclasses.
    receipts = []
    for value in values:
        receipts.append(
            IngestReceipt(
                company_id=header.company_id,
                status="accepted",
                source=SourceRevisionRef(
                    **value.source.model_dump(include=set(SourceRevisionRef.model_fields))
                ),
                artifact=ArtifactRevisionRef(
                    **value.artifact.model_dump(include=set(ArtifactRevisionRef.model_fields))
                ),
                parser_version=value.policy.parser_version,
                chunker_version=value.policy.chunker_version,
            )
        )
    output = PublishedCodingPatch(
        company_id=header.company_id,
        action_id=header.action_id,
        request_id=header.parameters.request_id,
        native_proposal_sha256=origin.native_proposal_sha256,
        origin=receipts[0],
        patch=receipts[1],
        origin_sha256=first.artifact.sha256,
        patch_sha256=last.artifact.sha256,
        admission_sha256=header.admission_sha256,
    )
    return PublicationPair(first, last, output, inputs, resources)


async def replay_pair(
    session: AsyncSession,
    scope: BrainReadScope,
    pair: PublicationPair,
    rules: CodingPublicationRules,
) -> bool:
    """Exact paired rows/heads/parse/edges or fail; never restore a source/grant by replay.

    Cohesion exception: no partial manifest comparison may license exact replay.
    """
    values = (pair.origin, pair.patch)
    rows = [
        await session.get(
            BrainArtifactRevision, (scope.company_id, value.artifact.artifact_revision_id)
        )
        for value in values
    ]
    sources = [
        await session.get(BrainSourceRevision, (scope.company_id, value.source.source_revision_id))
        for value in values
    ]
    if all(row is None for row in (*rows, *sources)):
        return False
    if any(row is None for row in (*rows, *sources)):
        raise ValueError("Coding publication has an incomplete immutable pair")
    for value, row, source in zip(values, rows, sources, strict=True):
        assert row and source and value.derivation and value.parsed
        if (
            artifact_record(row).model_dump() != value.artifact.model_dump()
            or row.data_classification != value.policy.data_classification
            or revision_record(source, value.artifact).model_dump(
                exclude={"ingested_at", "recorded_by"}
            )
            != value.source.model_dump(exclude={"ingested_at", "recorded_by"})
        ):
            raise ValueError("Coding publication immutable bytes/source replay differs")
        derivation = await session.get(
            BrainDerivation, (scope.company_id, value.derivation.derivation_id)
        )
        if (
            derivation is None
            or any(
                getattr(derivation, key) != getattr(value.derivation, key)
                for key in (
                    "kind",
                    "recipe_version",
                    "model_recipe",
                    "prompt_sha256",
                    "recorded_at",
                )
            )
            or derivation.artifact_revision_id != row.artifact_revision_id
        ):
            raise ValueError("Coding publication derivation replay differs")
        expected_inputs = pair.inputs if value is pair.origin else (pair.value.origin.artifact,)
        expected_resources = (
            pair.resources
            if value is pair.origin
            else (*pair.resources, rules.origin.resource.resource_id)
        )
        for model, parent, column, expected in (
            (
                BrainArtifactInput,
                BrainArtifactInput.artifact_revision_id,
                BrainArtifactInput.input_artifact_revision_id,
                {ref.artifact_revision_id for ref in expected_inputs},
            ),
            (
                BrainArtifactResourceInput,
                BrainArtifactResourceInput.artifact_revision_id,
                BrainArtifactResourceInput.resource_id,
                set(expected_resources),
            ),
            (
                BrainDerivationSource,
                BrainDerivationSource.derivation_id,
                BrainDerivationSource.source_revision_id,
                {ref.source_revision_id for ref in value.derivation.contributors},
            ),
            (
                BrainDerivationEvidence,
                BrainDerivationEvidence.derivation_id,
                BrainDerivationEvidence.evidence_id,
                {ref.evidence_id for ref in value.derivation.evidence},
            ),
        ):
            key = (
                value.derivation.derivation_id
                if model in (BrainDerivationSource, BrainDerivationEvidence)
                else row.artifact_revision_id
            )
            actual = set(
                (
                    await session.scalars(
                        select(column).where(model.company_id == scope.company_id, parent == key)
                    )
                ).all()
            )
            if actual != expected:
                raise ValueError("Coding publication complete input manifest replay differs")
        from nexus.company.brain.evidence_models import BrainParseRevision

        parsed = await session.get(
            BrainParseRevision, (scope.company_id, value.parsed.parse.parse_revision_id)
        )
        head = await session.get(BrainSourceHead, (scope.company_id, source.source_id))
        if (
            parsed is None
            or parsed.canonical_sha256 != value.artifact.sha256
            or parsed.canonical_text != value.artifact.raw_text
            or head is None
            or head.current_revision_id != source.source_revision_id
            or head.generation != 1
            or head.availability != "available"
            or head.fresh_until is not None
        ):
            raise ValueError("Coding publication current parse/head replay differs")
    return True


async def append_pair(
    session: AsyncSession,
    scope: BrainReadScope,
    pair: PublicationPair,
    rules: CodingPublicationRules,
    now: datetime,
) -> None:
    """Both source/head/parse/derivation/input sets commit in the caller's ONE owner transaction."""
    if await replay_pair(session, scope, pair, rules):
        return
    for value in (pair.origin, pair.patch):
        reference = value.artifact
        row = BrainArtifactRevision(
            **reference.model_dump(exclude={"resource", "schema_version", "recorded_at"}),
            resource_id=reference.resource.resource_id,
            recorded_at=reference.recorded_at,
            data_classification=value.policy.data_classification,
        )
        session.add(row)
        await session.flush()
        command = IngestCommand(
            company_id=scope.company_id,
            source_id=value.source.source_id,
            revision=value.source.revision,
            artifact=ArtifactRevisionRef(
                **reference.model_dump(include=set(ArtifactRevisionRef.model_fields))
            ),
        )
        head = await session.get(BrainSourceHead, (scope.company_id, value.source.source_id))
        if head is not None:
            raise ValueError("Coding new publication cannot replace a current source head")
        await _publish(session, scope, command, value, None, now)
        inputs = pair.inputs if value is pair.origin else (pair.value.origin.artifact,)
        resources = (
            pair.resources
            if value is pair.origin
            else (*pair.resources, rules.origin.resource.resource_id)
        )
        session.add_all(
            [
                BrainArtifactInput(
                    company_id=scope.company_id,
                    artifact_revision_id=reference.artifact_revision_id,
                    input_artifact_revision_id=ref.artifact_revision_id,
                )
                for ref in inputs
            ]
        )
        session.add_all(
            [
                BrainArtifactResourceInput(
                    company_id=scope.company_id,
                    artifact_revision_id=reference.artifact_revision_id,
                    resource_id=key,
                )
                for key in resources
            ]
        )
        await session.flush()
