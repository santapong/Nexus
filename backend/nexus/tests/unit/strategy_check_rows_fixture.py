"""Mocked immutable check graph; neither native SQL nor publication authority is exercised."""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.derivation_models import BrainDerivation
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.strategy import check_rows as module
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact, StrategyArtifactRule
from nexus.company.strategy.artifact_identity import strategy_derivation_id, strategy_reference
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.tests.unit.strategy_brief_fixture import strategy_case
from nexus.tests.unit.test_strategy_check_output import inputs


@dataclass
class CheckRowsCase:
    session: MagicMock
    scope: BrainReadScope
    action_id: UUID
    prepared: PreparedStrategyArtifact
    rule: StrategyArtifactRule
    policy: SourcePolicy
    artifact: BrainArtifactRevision
    derivation: BrainDerivation
    event: BrainEvent
    edges: list[list[UUID]]
    now: datetime


def rows_case(monkeypatch: pytest.MonkeyPatch) -> CheckRowsCase:
    # This >50-line fixture keeps complete byte/derivation/edge/event identity in one mock graph.
    command = strategy_case().command
    prepared = prepare_strategy_check(command, inputs(), "internal")
    company, action = command.company_id, UUID(int=980)
    scope = BrainReadScope(
        company_id=company,
        workspace_id=command.target.verifier.workspace_id,
        principal_id=command.target.verifier.actor_id,
        operation_id=UUID(int=981),
        trace_id=command.target.verifier.trace_id,
    )
    rule = StrategyArtifactRule(
        company_id=company,
        tool="company.cycle-artifact.check.v1",
        resource_symbol="strategy.check",
        target=ResourceRef(company_id=company, resource_id=UUID(int=982)),
        source_policy="generated.strategy-check.v1",
    )
    policy = SourcePolicy(
        source_symbol=rule.source_policy,
        authority_profile="fixture.derived.v1",
        origin_kind="derived",
        data_classification="internal",
        media_type="application/json",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        max_bytes=262144,
        freshness_seconds=None,
    )
    now = datetime.now(UTC)
    ref = strategy_reference(prepared, action)
    artifact = BrainArtifactRevision(
        company_id=company,
        artifact_id=ref.artifact_id,
        artifact_revision_id=ref.artifact_revision_id,
        revision=ref.revision,
        sha256=ref.sha256,
        byte_length=ref.byte_length,
        raw_text=prepared.raw_bytes.decode(),
        resource_id=rule.target.resource_id,
        derivation_id=strategy_derivation_id(company, action),
        media_type="application/json",
        storage_symbol="fixture.blobs.v1",
        data_classification="internal",
        recorded_at=now,
    )
    derivation = BrainDerivation(
        company_id=company,
        derivation_id=artifact.derivation_id,
        artifact_revision_id=ref.artifact_revision_id,
        recipe_version=prepared.recipe_version,
        kind="context",
        model_recipe=None,
        prompt_sha256=None,
        recorded_at=now,
    )
    event = BrainEvent(
        company_id=company,
        event_id=uuid5(company, f"strategy-check:{action}"),
        sequence=1,
        kind="derivation_changed",
        resource_id=rule.target.resource_id,
        action_id=action,
        deduplication_key=f"strategy-check:{action}",
        recorded_at=now,
    )
    edges = [
        [r.artifact_revision_id for r in prepared.inputs.artifacts],
        list(prepared.inputs.required_resource_ids),
        [r.source_revision_id for r in prepared.inputs.contributors],
        [r.evidence_id for r in prepared.inputs.evidence],
    ]
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True

    async def get(model: object, _: object) -> object:
        return (
            artifact
            if model is BrainArtifactRevision
            else derivation
            if model is BrainDerivation
            else None
        )

    cursor = {"index": 0}

    async def scalars(_: object) -> MagicMock:
        index = cursor["index"]
        cursor["index"] += 1
        result = MagicMock()
        result.all.return_value = edges[index]
        return result

    session.get = AsyncMock(side_effect=get)
    session.scalars = AsyncMock(side_effect=scalars)
    session.scalar = AsyncMock(return_value=event)
    monkeypatch.setattr(module, "validate_derivation", AsyncMock())
    monkeypatch.setattr(module, "save_derivation", AsyncMock())
    monkeypatch.setattr(module, "append_event", AsyncMock())
    return CheckRowsCase(
        session, scope, action, prepared, rule, policy, artifact, derivation, event, edges, now
    )
