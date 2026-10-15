"""Internal immutable C artifact graph; caller proves current issued SV publication authority."""

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
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact, StrategyArtifactRule
from nexus.company.strategy.artifact_identity import strategy_derivation_id, strategy_reference


async def require_strategy_check_replay_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    action_id: UUID,
    prepared: PreparedStrategyArtifact,
    rule: StrategyArtifactRule,
    storage_symbol: str,
) -> None:
    """A current caller must verify every exact immutable row/edge, not just result bytes."""
    reference = strategy_reference(prepared, action_id)
    require_acceptance(
        session.in_transaction() and scope.company_id == prepared.company_id == rule.company_id
    )
    row = await session.get(
        BrainArtifactRevision, (scope.company_id, reference.artifact_revision_id)
    )
    require_acceptance(row is not None)
    assert row is not None
    require_acceptance(
        (
            row.company_id,
            row.artifact_id,
            row.artifact_revision_id,
            row.revision,
            row.raw_text,
            row.sha256,
            row.byte_length,
            row.resource_id,
            row.derivation_id,
            row.media_type,
            row.storage_symbol,
            row.data_classification,
        )
        == (
            reference.company_id,
            reference.artifact_id,
            reference.artifact_revision_id,
            reference.revision,
            prepared.raw_bytes.decode(),
            reference.sha256,
            reference.byte_length,
            rule.target.resource_id,
            strategy_derivation_id(scope.company_id, action_id),
            "application/json",
            storage_symbol,
            prepared.data_classification,
        )
    )
    await _require_derivation(session, scope, action_id, prepared, row.recorded_at)
    await _require_edges(session, scope, action_id, prepared)
    event = await session.scalar(
        select(BrainEvent).where(
            BrainEvent.company_id == scope.company_id,
            BrainEvent.deduplication_key == f"strategy-check:{action_id}",
        )
    )
    require_acceptance(
        event is not None
        and event.event_id == uuid5(scope.company_id, f"strategy-check:{action_id}")
        and event.company_id == scope.company_id
        and event.deduplication_key == f"strategy-check:{action_id}"
        and event.kind == "derivation_changed"
        and event.resource_id == rule.target.resource_id
        and event.action_id == action_id
        and event.recorded_at == row.recorded_at
    )


async def _require_derivation(
    session: AsyncSession,
    scope: BrainReadScope,
    action_id: UUID,
    prepared: PreparedStrategyArtifact,
    recorded_at: datetime,
) -> None:
    reference = strategy_reference(prepared, action_id)
    key = strategy_derivation_id(scope.company_id, action_id)
    row = await session.get(BrainDerivation, (scope.company_id, key))
    require_acceptance(row is not None)
    assert row is not None
    require_acceptance(
        row.company_id == scope.company_id
        and row.derivation_id == key
        and row.artifact_revision_id == reference.artifact_revision_id
        and row.recipe_version == prepared.recipe_version
        and row.kind == "context"
        and row.model_recipe is None
        and row.prompt_sha256 is None
        and row.recorded_at == recorded_at
    )


async def _require_edges(
    session: AsyncSession,
    scope: BrainReadScope,
    action_id: UUID,
    prepared: PreparedStrategyArtifact,
) -> None:
    artifact = strategy_reference(prepared, action_id).artifact_revision_id
    derivation = strategy_derivation_id(scope.company_id, action_id)
    inputs = prepared.inputs
    groups = (
        (
            BrainArtifactInput,
            BrainArtifactInput.artifact_revision_id,
            BrainArtifactInput.input_artifact_revision_id,
            artifact,
            {row.artifact_revision_id for row in inputs.artifacts},
        ),
        (
            BrainArtifactResourceInput,
            BrainArtifactResourceInput.artifact_revision_id,
            BrainArtifactResourceInput.resource_id,
            artifact,
            set(inputs.required_resource_ids),
        ),
        (
            BrainDerivationSource,
            BrainDerivationSource.derivation_id,
            BrainDerivationSource.source_revision_id,
            derivation,
            {row.source_revision_id for row in inputs.contributors},
        ),
        (
            BrainDerivationEvidence,
            BrainDerivationEvidence.derivation_id,
            BrainDerivationEvidence.evidence_id,
            derivation,
            {row.evidence_id for row in inputs.evidence},
        ),
    )
    for model, parent, column, key, expected in groups:
        values = tuple(
            (
                await session.scalars(
                    select(column)
                    .where(model.company_id == scope.company_id, parent == key)
                    .limit(len(expected) + 1)
                )
            ).all()
        )
        require_acceptance(len(values) == len(expected) and set(values) == expected)


async def write_strategy_check_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    action_id: UUID,
    prepared: PreparedStrategyArtifact,
    rule: StrategyArtifactRule,
    policy: SourcePolicy,
    storage_symbol: str,
    now: datetime,
) -> None:
    """Append one check graph under the actual store's CompanyControl transaction and gate."""
    # Keep this >50-line single graph/derivation/edge/event append in one rollback boundary.
    reference = strategy_reference(prepared, action_id)
    require_acceptance(
        session.in_transaction()
        and scope.company_id == prepared.company_id == rule.company_id
        and rule.tool == "company.cycle-artifact.check.v1"
        and policy.source_symbol == rule.source_policy
        and policy.origin_kind == "derived"
        and policy.media_type == "application/json"
        and policy.data_classification == prepared.data_classification
        and len(prepared.raw_bytes) <= policy.max_bytes
        and await session.get(
            BrainArtifactRevision, (scope.company_id, reference.artifact_revision_id)
        )
        is None
    )
    value = DerivationRecord(
        company_id=scope.company_id,
        derivation_id=strategy_derivation_id(scope.company_id, action_id),
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
            artifact_id=reference.artifact_id,
            artifact_revision_id=reference.artifact_revision_id,
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
                resource_id=key,
            )
            for key in prepared.inputs.required_resource_ids
        ]
    )
    await session.flush()
    await append_event(
        session,
        scope,
        kind="derivation_changed",
        resource_id=rule.target.resource_id,
        action_id=action_id,
        deduplication_key=f"strategy-check:{action_id}",
        now=now,
    )
