"""Atomic ordered P/C outputs and complete immutable provenance/event replay."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import (
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
)
from nexus.company.brain.derivation_support import save_derivation, validate_derivation
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import append_event
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.cycle_artifacts.production import PreparedCycleDeliverable
from nexus.company.cycle_artifacts.publication_contracts import (
    CycleArtifactRule,
    PreparedCycleCheck,
)
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs


@dataclass(frozen=True)
class CyclePublicationLayout:
    reference: ArtifactRevisionRef
    raw: bytes
    inputs: GeneratedArtifactInputs
    policy: SourcePolicy
    target_id: UUID
    action_id: UUID
    recipe: str
    event_key: str
    trace_id: UUID

    @property
    def derivation_id(self) -> UUID:
        return uuid5(self.reference.artifact_id, "derivation:v1")


def author_layout(
    prepared: PreparedCycleDeliverable,
    rule: CycleArtifactRule,
) -> tuple[CyclePublicationLayout, ...]:
    """Both ordered exports share the unchanged M; neither adds a future self reference."""
    prepared = PreparedCycleDeliverable.model_validate(prepared.model_dump(warnings=False))
    require_acceptance(
        rule.phase == "write"
        and rule.kind == prepared.basis.artifact_kind
        and rule.company_id == prepared.basis.company_id
        and rule.target == prepared.basis.target
    )
    rows = []
    for part, body in zip(
        prepared.manifest.parts, (prepared.typed_json, prepared.human_export), strict=True
    ):
        policy = rule.policy(part.part)
        require_acceptance(
            policy.data_classification == prepared.basis.data_classification
            and len(body) <= policy.max_bytes
        )
        rows.append(
            CyclePublicationLayout(
                part.artifact,
                body,
                prepared.basis.inputs,
                policy,
                rule.target.resource_id,
                prepared.action_id,
                rule.recipe_version,
                f"cycle-deliverable:{rule.kind}:{prepared.action_id}:{part.part}",
                prepared.basis.author.trace_id,
            )
        )
    return tuple(rows)


def check_layout(prepared: PreparedCycleCheck, rule: CycleArtifactRule) -> CyclePublicationLayout:
    """The protected check retains M plus both ordered author outputs."""
    prepared = PreparedCycleCheck.model_validate(prepared.model_dump(warnings=False))
    policy = rule.policy("check")
    require_acceptance(
        rule.phase == "check"
        and rule.kind == prepared.command.artifact_kind
        and rule.company_id == prepared.command.company_id
        and policy.data_classification == prepared.classification
        and len(prepared.raw_bytes) <= policy.max_bytes
    )
    return CyclePublicationLayout(
        prepared.artifact,
        prepared.raw_bytes,
        prepared.inputs,
        policy,
        rule.target.resource_id,
        prepared.action_id,
        rule.recipe_version,
        f"cycle-check:{rule.kind}:{prepared.action_id}",
        prepared.command.target.verifier.trace_id,
    )


def require_row(row: BrainArtifactRevision, layout: CyclePublicationLayout, storage: str) -> None:
    """Compare all immutable byte, identity, media, classification and target fields."""
    ref = layout.reference
    require_acceptance(
        (
            row.company_id,
            row.artifact_id,
            row.artifact_revision_id,
            row.revision,
            row.sha256,
            row.byte_length,
            row.raw_text,
            row.resource_id,
            row.derivation_id,
            row.media_type,
            row.storage_symbol,
            row.data_classification,
        )
        == (
            ref.company_id,
            ref.artifact_id,
            ref.artifact_revision_id,
            ref.revision,
            ref.sha256,
            ref.byte_length,
            layout.raw.decode(),
            layout.target_id,
            layout.derivation_id,
            layout.policy.media_type,
            storage,
            layout.policy.data_classification,
        )
    )


async def _edges(
    session: AsyncSession, scope: BrainReadScope, layout: CyclePublicationLayout
) -> None:
    """Read every edge family with a one-extra bound before matching complete sets."""
    inputs, ref = layout.inputs, layout.reference
    groups = (
        (
            BrainArtifactInput,
            BrainArtifactInput.artifact_revision_id,
            BrainArtifactInput.input_artifact_revision_id,
            ref.artifact_revision_id,
            {r.artifact_revision_id for r in inputs.artifacts},
        ),
        (
            BrainArtifactResourceInput,
            BrainArtifactResourceInput.artifact_revision_id,
            BrainArtifactResourceInput.resource_id,
            ref.artifact_revision_id,
            set(inputs.required_resource_ids),
        ),
        (
            BrainDerivationSource,
            BrainDerivationSource.derivation_id,
            BrainDerivationSource.source_revision_id,
            layout.derivation_id,
            {r.source_revision_id for r in inputs.contributors},
        ),
        (
            BrainDerivationEvidence,
            BrainDerivationEvidence.derivation_id,
            BrainDerivationEvidence.evidence_id,
            layout.derivation_id,
            {r.evidence_id for r in inputs.evidence},
        ),
    )
    for model, parent, column, key, expected in groups:
        values = tuple(
            (
                await session.scalars(
                    select(column)
                    .where(
                        model.company_id == scope.company_id,
                        parent == key,
                    )
                    .limit(len(expected) + 1)
                )
            ).all()
        )
        require_acceptance(len(values) == len(expected) and set(values) == expected)


async def _replay(
    session: AsyncSession,
    scope: BrainReadScope,
    layouts: tuple[CyclePublicationLayout, ...],
    storage: str,
) -> None:
    # Every row/derivation/four edge families/event is one cohesive >50-line immutable replay.
    require_acceptance(session.in_transaction())
    for layout in layouts:
        ref = layout.reference
        require_acceptance(scope.company_id == ref.company_id)
        row = await session.get(BrainArtifactRevision, (scope.company_id, ref.artifact_revision_id))
        require_acceptance(row is not None)
        assert row is not None
        require_row(row, layout, storage)
        derivation = await session.get(BrainDerivation, (scope.company_id, layout.derivation_id))
        require_acceptance(derivation is not None)
        assert derivation is not None
        require_acceptance(
            (
                derivation.company_id,
                derivation.derivation_id,
                derivation.artifact_revision_id,
                derivation.kind,
                derivation.recipe_version,
                derivation.model_recipe,
                derivation.prompt_sha256,
                derivation.recorded_at,
            )
            == (
                scope.company_id,
                layout.derivation_id,
                ref.artifact_revision_id,
                "context",
                layout.recipe,
                None,
                None,
                row.recorded_at,
            )
        )
        await _edges(session, scope, layout)
        event = await session.get(
            BrainEvent, (scope.company_id, uuid5(scope.company_id, layout.event_key))
        )
        require_acceptance(event is not None)
        assert event is not None
        require_acceptance(
            (
                event.company_id,
                event.event_id,
                event.kind,
                event.resource_id,
                event.action_id,
                event.deduplication_key,
                event.source_revision_id,
                event.resource_generation,
                event.recorded_at,
                event.trace_id,
                event.operation_id,
            )
            == (
                scope.company_id,
                uuid5(scope.company_id, layout.event_key),
                "derivation_changed",
                layout.target_id,
                layout.action_id,
                layout.event_key,
                None,
                None,
                row.recorded_at,
                layout.trace_id,
                uuid5(layout.action_id, "cycle-publication:v1"),
            )
        )


async def _append(
    session: AsyncSession,
    scope: BrainReadScope,
    layouts: tuple[CyclePublicationLayout, ...],
    storage: str,
    now: datetime,
) -> None:
    # Preflight every absent member before appending either graph; caller owns atomic rollback.
    require_acceptance(session.in_transaction() and now.utcoffset() is not None)
    present = []
    for layout in layouts:
        require_acceptance(scope.company_id == layout.reference.company_id)
        present.append(
            await session.get(
                BrainArtifactRevision, (scope.company_id, layout.reference.artifact_revision_id)
            )
        )
    require_acceptance(all(row is None for row in present))
    for layout in layouts:
        ref, inputs = layout.reference, layout.inputs
        value = DerivationRecord(
            company_id=scope.company_id,
            derivation_id=layout.derivation_id,
            artifact=ref,
            kind="context",
            recipe_version=layout.recipe,
            contributors=inputs.contributors,
            evidence=inputs.evidence,
            recorded_at=now,
        )
        await validate_derivation(session, scope, value, ref, layout.target_id, layout.policy, now)
        session.add(
            BrainArtifactRevision(
                company_id=scope.company_id,
                artifact_id=ref.artifact_id,
                artifact_revision_id=ref.artifact_revision_id,
                revision=ref.revision,
                resource_id=layout.target_id,
                media_type=layout.policy.media_type,
                storage_symbol=storage,
                raw_text=layout.raw.decode(),
                sha256=ref.sha256,
                byte_length=ref.byte_length,
                derivation_id=layout.derivation_id,
                data_classification=layout.policy.data_classification,
                recorded_at=now,
            )
        )
        await session.flush()
        await save_derivation(session, value)
        session.add_all(
            [
                BrainArtifactInput(
                    company_id=scope.company_id,
                    artifact_revision_id=ref.artifact_revision_id,
                    input_artifact_revision_id=r.artifact_revision_id,
                )
                for r in inputs.artifacts
            ]
        )
        session.add_all(
            [
                BrainArtifactResourceInput(
                    company_id=scope.company_id,
                    artifact_revision_id=ref.artifact_revision_id,
                    resource_id=key,
                )
                for key in inputs.required_resource_ids
            ]
        )
        await session.flush()
        await append_event(
            session,
            scope,
            kind="derivation_changed",
            resource_id=layout.target_id,
            action_id=layout.action_id,
            deduplication_key=layout.event_key,
            now=now,
        )


async def append_author_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedCycleDeliverable,
    rule: CycleArtifactRule,
    storage: str,
    now: datetime,
) -> None:
    """Append exactly two absent graphs in the caller's existing company transaction."""
    await _append(session, scope, author_layout(prepared, rule), storage, now)


async def require_author_replay_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedCycleDeliverable,
    rule: CycleArtifactRule,
    storage: str,
) -> None:
    """Require both immutable output graphs; partial repair is never allowed."""
    await _replay(session, scope, author_layout(prepared, rule), storage)


async def append_check_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedCycleCheck,
    rule: CycleArtifactRule,
    storage: str,
    now: datetime,
) -> None:
    """Append one protected check graph after actual issued verifier qualification."""
    await _append(session, scope, (check_layout(prepared, rule),), storage, now)


async def require_check_replay_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedCycleCheck,
    rule: CycleArtifactRule,
    storage: str,
) -> None:
    """Compare complete check bytes, M+two-output edges and original event."""
    await _replay(session, scope, (check_layout(prepared, rule),), storage)
