"""Immutable artifact/derivation/input edges/outbox rows; no source head or M1 receipt mutation."""

from datetime import datetime
from uuid import UUID

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
from nexus.company.brain.event_store import append_event
from nexus.company.brain.scope_support import BrainConflictError
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.company.management.generated_artifact_identity import generated_derivation_id


async def require_generated_replay(
    session: AsyncSession,
    row: BrainArtifactRevision,
    reference: ArtifactRevisionRef,
    prepared: GeneratedArtifactPayload,
    rule: GeneratedArtifactRule,
    action_id: UUID,
    storage_symbol: str,
) -> None:
    """A known immutable output must preserve exact bytes, target, recipe and every edge."""
    expected = generated_derivation_id(prepared.company_id, action_id)
    if (
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
    ) != (
        reference.artifact_id,
        reference.artifact_revision_id,
        reference.revision,
        reference.sha256,
        reference.byte_length,
        prepared.raw_bytes.decode(),
        rule.target.resource_id,
        expected,
        "application/json",
        storage_symbol,
        prepared.data_classification,
    ):
        raise BrainConflictError(
            "Known generated output cannot replace bytes, target or classification"
        )
    derivation = await session.get(BrainDerivation, (prepared.company_id, expected))
    if (
        derivation is None
        or derivation.artifact_revision_id != reference.artifact_revision_id
        or derivation.recipe_version != prepared.recipe_version
        or derivation.kind != "context"
        or derivation.model_recipe is not None
        or derivation.prompt_sha256 is not None
    ):
        raise BrainConflictError("Known generated derivation differs from exact native recipe")
    groups = (
        (
            BrainArtifactInput,
            BrainArtifactInput.artifact_revision_id,
            BrainArtifactInput.input_artifact_revision_id,
            {value.artifact_revision_id for value in prepared.inputs.artifacts},
        ),
        (
            BrainArtifactResourceInput,
            BrainArtifactResourceInput.artifact_revision_id,
            BrainArtifactResourceInput.resource_id,
            set(prepared.inputs.required_resource_ids),
        ),
        (
            BrainDerivationSource,
            BrainDerivationSource.derivation_id,
            BrainDerivationSource.source_revision_id,
            {value.source_revision_id for value in prepared.inputs.contributors},
        ),
        (
            BrainDerivationEvidence,
            BrainDerivationEvidence.derivation_id,
            BrainDerivationEvidence.evidence_id,
            {value.evidence_id for value in prepared.inputs.evidence},
        ),
    )
    for model, parent, column, expected_values in groups:
        key = (
            reference.artifact_revision_id
            if model in (BrainArtifactInput, BrainArtifactResourceInput)
            else expected
        )
        actual = set(
            (
                await session.scalars(
                    select(column).where(model.company_id == prepared.company_id, parent == key)
                )
            ).all()
        )
        if actual != expected_values:
            raise BrainConflictError("Known generated output lacks its exact complete input edges")


async def write_generated_rows(
    session: AsyncSession,
    scope: BrainReadScope,
    reference: ArtifactRevisionRef,
    prepared: GeneratedArtifactPayload,
    rule: GeneratedArtifactRule,
    policy: SourcePolicy,
    action_id: UUID,
    storage_symbol: str,
    now: datetime,
) -> None:
    """Public validated derivation and artifact metadata commit together with all privacy edges."""
    # Keep the >50-line native artifact/derivation/edge/event append in one transaction.
    value = DerivationRecord(
        company_id=scope.company_id,
        derivation_id=generated_derivation_id(scope.company_id, action_id),
        artifact=reference,
        recipe_version=prepared.recipe_version,
        kind="context",
        contributors=prepared.inputs.contributors,
        evidence=prepared.inputs.evidence,
        recorded_at=now,
    )
    await validate_derivation(
        session, scope, value, reference, rule.target.resource_id, policy, now
    )
    session.add(
        BrainArtifactRevision(
            company_id=scope.company_id,
            artifact_revision_id=reference.artifact_revision_id,
            artifact_id=reference.artifact_id,
            revision=reference.revision,
            resource_id=rule.target.resource_id,
            media_type=policy.media_type,
            storage_symbol=storage_symbol,
            raw_text=prepared.raw_bytes.decode(),
            sha256=reference.sha256,
            byte_length=reference.byte_length,
            derivation_id=value.derivation_id,
            data_classification=prepared.data_classification,
            recorded_at=now,
        )
    )
    await session.flush()
    await save_derivation(session, value)
    session.add_all(
        [
            BrainArtifactInput(
                company_id=scope.company_id,
                artifact_revision_id=reference.artifact_revision_id,
                input_artifact_revision_id=row.artifact_revision_id,
            )
            for row in prepared.inputs.artifacts
        ]
    )
    session.add_all(
        [
            BrainArtifactResourceInput(
                company_id=scope.company_id,
                artifact_revision_id=reference.artifact_revision_id,
                resource_id=resource,
            )
            for resource in prepared.inputs.required_resource_ids
        ]
    )
    await session.flush()
    await append_event(
        session,
        scope,
        kind="derivation_changed",
        resource_id=rule.target.resource_id,
        action_id=action_id,
        deduplication_key=f"generated-artifact:{action_id}",
        now=now,
    )
