"""Internal exact B/Brief row graphs; the concrete store owns current effect authority."""

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
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.artifact_identity import strategy_derivation_id
from nexus.company.strategy.publication_contracts import PreparedStrategyPublication
from nexus.company.strategy.publication_identity import strategy_bundle_derivation_id


@dataclass(frozen=True)
class StrategyArtifactLayout:
    """Exact row projection; it is not an authorization witness."""

    reference: ArtifactRevisionRef
    raw: bytes
    derivation_id: UUID
    recipe: str
    inputs: tuple[ArtifactRevisionRef, ...]
    event_key: str


def publication_layout(prepared: PreparedStrategyPublication) -> tuple[StrategyArtifactLayout, ...]:
    """Keep B->M and Brief->M+B explicit without modifying the original prepared manifest."""
    company, action = prepared.original.company_id, prepared.action_id
    bundle = prepared.compiled.original_bundle.artifact
    inputs = prepared.original.snapshot.inputs.artifacts
    return (
        StrategyArtifactLayout(
            bundle,
            prepared.bundle_bytes,
            strategy_bundle_derivation_id(company, action),
            "strategy-input-bundle-json-v2",
            inputs,
            f"strategy-bundle:{action}",
        ),
        StrategyArtifactLayout(
            prepared.brief,
            prepared.compiled.prepared.raw_bytes,
            strategy_derivation_id(company, action),
            prepared.compiled.prepared.recipe_version,
            (*inputs, bundle),
            f"strategy-brief:{action}",
        ),
    )


def require_artifact_row(
    row: BrainArtifactRevision,
    layout: StrategyArtifactLayout,
    prepared: PreparedStrategyPublication,
    storage_symbol: str,
) -> None:
    """Compare every immutable byte/identity/target/classification field."""
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
            prepared.compiled.original_bundle.resource.resource_id,
            layout.derivation_id,
            "application/json",
            storage_symbol,
            prepared.compiled.prepared.data_classification,
        )
    )


async def require_layout_edges_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    inputs: GeneratedArtifactInputs,
    layout: StrategyArtifactLayout,
) -> None:
    """Compare all four edge sets against the complete declared native input view."""
    # The four exact relations form one cohesive >50-line provenance comparison.
    groups = (
        (
            BrainArtifactInput,
            BrainArtifactInput.artifact_revision_id,
            BrainArtifactInput.input_artifact_revision_id,
            layout.reference.artifact_revision_id,
            {row.artifact_revision_id for row in layout.inputs},
        ),
        (
            BrainArtifactResourceInput,
            BrainArtifactResourceInput.artifact_revision_id,
            BrainArtifactResourceInput.resource_id,
            layout.reference.artifact_revision_id,
            set(inputs.required_resource_ids),
        ),
        (
            BrainDerivationSource,
            BrainDerivationSource.derivation_id,
            BrainDerivationSource.source_revision_id,
            layout.derivation_id,
            {row.source_revision_id for row in inputs.contributors},
        ),
        (
            BrainDerivationEvidence,
            BrainDerivationEvidence.derivation_id,
            BrainDerivationEvidence.evidence_id,
            layout.derivation_id,
            {row.evidence_id for row in inputs.evidence},
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


async def require_strategy_publication_replay_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedStrategyPublication,
    storage_symbol: str,
) -> None:
    """Both complete graphs and outbox mirrors must exist; partial repair is forbidden."""
    # This >50-line replay keeps both immutable row graphs and event mirrors together.
    require_acceptance(
        session.in_transaction() and scope.company_id == prepared.original.company_id
    )
    for layout in publication_layout(prepared):
        row = await session.get(
            BrainArtifactRevision, (scope.company_id, layout.reference.artifact_revision_id)
        )
        require_acceptance(row is not None)
        assert row is not None
        require_artifact_row(row, layout, prepared, storage_symbol)
        derivation = await session.get(BrainDerivation, (scope.company_id, layout.derivation_id))
        require_acceptance(derivation is not None)
        assert derivation is not None
        require_acceptance(
            (
                derivation.artifact_revision_id,
                derivation.kind,
                derivation.recipe_version,
                derivation.model_recipe,
                derivation.prompt_sha256,
                derivation.recorded_at,
            )
            == (
                layout.reference.artifact_revision_id,
                "context",
                layout.recipe,
                None,
                None,
                row.recorded_at,
            )
        )
        await require_layout_edges_locked(session, scope, prepared.original.snapshot.inputs, layout)
        event = await session.get(
            BrainEvent, (scope.company_id, uuid5(scope.company_id, layout.event_key))
        )
        require_acceptance(event is not None)
        assert event is not None
        require_acceptance(
            (
                event.kind,
                event.resource_id,
                event.action_id,
                event.deduplication_key,
                event.source_revision_id,
                event.resource_generation,
                event.recorded_at,
                event.trace_id,
            )
            == (
                "derivation_changed",
                row.resource_id,
                prepared.action_id,
                layout.event_key,
                None,
                None,
                row.recorded_at,
                prepared.original.snapshot.scope.author.trace_id,
            )
        )


async def write_strategy_publication_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedStrategyPublication,
    rule: StrategyArtifactRule,
    bundle_policy: SourcePolicy,
    brief_policy: SourcePolicy,
    storage_symbol: str,
    now: datetime,
) -> None:
    """Append only within the store's actual issued actor gate and supplied company transaction."""
    # This cohesive >50-line append keeps two native graphs and their events in one transaction.
    require_acceptance(
        session.in_transaction() and scope.company_id == prepared.original.company_id
    )
    inputs = prepared.original.snapshot.inputs
    for layout, policy in zip(
        publication_layout(prepared), (bundle_policy, brief_policy), strict=True
    ):
        require_acceptance(
            await session.get(
                BrainArtifactRevision, (scope.company_id, layout.reference.artifact_revision_id)
            )
            is None
        )
        value = DerivationRecord(
            company_id=scope.company_id,
            derivation_id=layout.derivation_id,
            artifact=layout.reference,
            recipe_version=layout.recipe,
            kind="context",
            contributors=inputs.contributors,
            evidence=inputs.evidence,
            recorded_at=now,
        )
        await validate_derivation(
            session, scope, value, layout.reference, rule.target.resource_id, policy, now
        )
        session.add(
            BrainArtifactRevision(
                company_id=scope.company_id,
                artifact_revision_id=layout.reference.artifact_revision_id,
                artifact_id=layout.reference.artifact_id,
                revision=layout.reference.revision,
                resource_id=rule.target.resource_id,
                media_type="application/json",
                storage_symbol=storage_symbol,
                raw_text=layout.raw.decode(),
                sha256=layout.reference.sha256,
                byte_length=len(layout.raw),
                derivation_id=layout.derivation_id,
                data_classification=prepared.compiled.prepared.data_classification,
                recorded_at=now,
            )
        )
        await session.flush()
        await save_derivation(session, value)
        session.add_all(
            [
                BrainArtifactInput(
                    company_id=scope.company_id,
                    artifact_revision_id=layout.reference.artifact_revision_id,
                    input_artifact_revision_id=row.artifact_revision_id,
                )
                for row in layout.inputs
            ]
        )
        session.add_all(
            [
                BrainArtifactResourceInput(
                    company_id=scope.company_id,
                    artifact_revision_id=layout.reference.artifact_revision_id,
                    resource_id=resource,
                )
                for resource in inputs.required_resource_ids
            ]
        )
        await session.flush()
        await append_event(
            session,
            scope,
            kind="derivation_changed",
            resource_id=rule.target.resource_id,
            action_id=prepared.action_id,
            deduplication_key=layout.event_key,
            now=now,
        )
