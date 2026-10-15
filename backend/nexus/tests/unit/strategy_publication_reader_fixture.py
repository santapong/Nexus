"""Actual-shaped protected rows with delegated source checks; no PostgreSQL authority proof."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid5

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.derivation_models import (
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
)
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSource
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.plan_catalog import NamedPlanResource, PlanAdmissionCatalog
from nexus.company.strategy.artifact_contracts import (
    StrategyArtifactRule,
    StrategyBriefSelector,
    StrategyWriteParameters,
)
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_contracts import PreparedStrategyPublication
from nexus.company.strategy.publication_identity import prepare_strategy_publication
from nexus.company.strategy.publication_rows import publication_layout
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.strategy_producer_fixture import producer_case
from nexus.tests.unit.strategy_source_inputs_fixture import SourceCase, source_case


class Policies:
    def __init__(self, values: tuple[SourcePolicy, ...]) -> None:
        self.values = {row.source_symbol: row for row in values}

    def policy(self, symbol: str) -> SourcePolicy:
        return self.values[symbol]


@dataclass
class ReaderCase:
    source: SourceCase
    reader: StrategyInputReader
    prepared: PreparedStrategyPublication
    rows: dict[tuple[type[object], object], object]
    edges: dict[tuple[str, UUID], list[UUID]]
    action: ActionProposal
    effect: EffectIntent
    row_get: AsyncMock


def reader_case(monkeypatch: pytest.MonkeyPatch) -> ReaderCase:
    # This >50-line fixture keeps native bytes, edges and receipt chronology coherent.
    from nexus.company.strategy import input_reader, publication_protection

    source = source_case(monkeypatch)
    snapshot = source.original
    _, policy = producer_case()
    company, bound = snapshot.company_id, snapshot.scope.author
    targets = (
        ResourceRef(company_id=company, resource_id=UUID(int=500)),
        ResourceRef(company_id=company, resource_id=UUID(int=510)),
    )
    write = StrategyArtifactRule(
        company_id=company,
        tool="company.cycle-artifact.write.v1",
        resource_symbol="strategy.output",
        target=targets[0],
        source_policy="generated.strategy.v1",
    )
    check = StrategyArtifactRule(
        company_id=company,
        tool="company.cycle-artifact.check.v1",
        resource_symbol="strategy.check",
        target=targets[1],
        source_policy="generated.strategy-check.v1",
    )
    base = SourcePolicy(
        source_symbol="generated.strategy-inputs.v2",
        authority_profile="fixture",
        data_classification="internal",
        origin_kind="derived",
        media_type="application/json",
        parser_version="json-v1",
        chunker_version="utf8-v1",
        search_config="simple",
        freshness_seconds=None,
    )
    policies = Policies(
        (
            base,
            base.model_copy(update={"source_symbol": write.source_policy, "max_bytes": 262144}),
            base.model_copy(update={"source_symbol": check.source_policy, "max_bytes": 262144}),
            snapshot.sources[0].source_policy,
        )
    )
    catalog = PlanAdmissionCatalog(
        company_id=company,
        models=ModelRegistry(company_id=company, revision="fixture", pricebook_version="p1"),
        admitted_profiles=frozenset({"reasoning", "verification"}),
        check_recipes=frozenset({"stockflow-strategy-brief-v1"}),
        tools=tuple(
            ToolPermission(tool=row.tool, tool_version="v1", resource=row.resource_symbol)
            for row in (write, check)
        ),
        resources=tuple(
            NamedPlanResource(symbol=row.resource_symbol, resource=row.target)
            for row in (write, check)
        ),
    )
    blobs = MagicMock()
    blobs.storage_symbol = "fixture"
    artifacts = MagicMock(spec=BoundedArtifactReader)
    artifacts.blobs, artifacts.factory = blobs, MagicMock()
    artifacts.revalidate_artifact_reference = AsyncMock()
    reader = StrategyInputReader(
        artifacts, policies, catalog, policy, blobs=blobs, write_rule=write, check_rule=check
    )
    prepared = prepare_strategy_publication(snapshot, policy, UUID(int=501), targets[0])
    now = source.clock["now"]
    action = ActionProposal(
        company_id=company,
        action_id=prepared.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        actor_id=bound.actor_id,
        revision=1,
        tool=write.tool,
        tool_version="v1",
        resource=write.resource_symbol,
        parameters=StrategyWriteParameters(
            selector=StrategyBriefSelector(scope=snapshot.scope),
            output_sha256=prepared.brief.sha256,
            input_snapshot_sha256=prepared.compiled.prepared.input_snapshot_sha256,
            input_manifest_sha256=prepared.compiled.prepared.input_manifest_sha256,
        ).model_dump(mode="json"),
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    receipt = ActionReceipt(
        company_id=company,
        receipt_id=UUID(int=801),
        action_id=action.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_hash=action_hash(action),
        outcome="succeeded",
        recorded_at=now + timedelta(seconds=3),
        artifacts=(
            ArtifactRef(
                company_id=company,
                artifact_id=prepared.brief.artifact_id,
                reference=f"artifact:{prepared.brief.artifact_revision_id}",
                revision=prepared.brief.revision,
                sha256=prepared.brief.sha256,
            ),
        ),
    )
    effect = EffectIntent(
        company_id=company,
        action_id=action.action_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        proposal_hash=action_hash(action),
        intent_fence=1,
        attempt_kind="tool_attempts",
        created_at=now - timedelta(seconds=1),
        state="succeeded",
        receipt_json=receipt.model_dump_json(),
    )
    journal = JournalAction(
        id=action.action_id,
        company_id=company,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        proposal_json=action.model_dump_json(),
        proposal_hash=action_hash(action),
        state="authorized",
        consumed_at=now - timedelta(seconds=3),
    )
    attempt = ExecutionAttempt(
        company_id=company,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        attempt_id=action.action_id,
        kind="tool_attempts",
        fence=1,
        reserved_at=now - timedelta(seconds=2),
    )
    hold = CostHold(
        company_id=company,
        action_id=action.action_id,
        task_id=bound.task_id,
        state="unknown",
        amount_usd=Decimal(".01"),
        actual_usd=None,
    )
    rows: dict[tuple[type[object], object], object] = {
        (JournalAction, action.action_id): journal,
        (EffectIntent, (company, action.action_id)): effect,
        (ExecutionAttempt, (company, bound.task_id, action.action_id)): attempt,
        (CostHold, action.action_id): hold,
    }
    edges: dict[tuple[str, UUID], list[UUID]] = {}
    for layout in publication_layout(prepared):
        ref = layout.reference
        rows[(BrainArtifactRevision, (company, ref.artifact_revision_id))] = BrainArtifactRevision(
            company_id=company,
            artifact_revision_id=ref.artifact_revision_id,
            artifact_id=ref.artifact_id,
            revision=ref.revision,
            sha256=ref.sha256,
            byte_length=ref.byte_length,
            raw_text=layout.raw.decode(),
            resource_id=targets[0].resource_id,
            derivation_id=layout.derivation_id,
            media_type="application/json",
            storage_symbol="fixture",
            data_classification="internal",
            recorded_at=now + timedelta(seconds=2),
        )
        rows[(BrainDerivation, (company, layout.derivation_id))] = BrainDerivation(
            company_id=company,
            derivation_id=layout.derivation_id,
            artifact_revision_id=ref.artifact_revision_id,
            recipe_version=layout.recipe,
            kind="context",
            model_recipe=None,
            prompt_sha256=None,
            recorded_at=now + timedelta(seconds=2),
        )
        rows[(BrainEvent, (company, uuid5(company, layout.event_key)))] = BrainEvent(
            company_id=company,
            event_id=uuid5(company, layout.event_key),
            kind="derivation_changed",
            resource_id=targets[0].resource_id,
            action_id=action.action_id,
            deduplication_key=layout.event_key,
            source_revision_id=None,
            resource_generation=None,
            trace_id=bound.trace_id,
            recorded_at=now + timedelta(seconds=2),
        )
        edges[(BrainArtifactInput.__tablename__, ref.artifact_revision_id)] = [
            row.artifact_revision_id for row in layout.inputs
        ]
        edges[(BrainArtifactResourceInput.__tablename__, ref.artifact_revision_id)] = list(
            snapshot.inputs.required_resource_ids
        )
        edges[(BrainDerivationSource.__tablename__, layout.derivation_id)] = [
            row.source_revision_id for row in snapshot.inputs.contributors
        ]
        edges[(BrainDerivationEvidence.__tablename__, layout.derivation_id)] = [
            row.evidence_id for row in snapshot.inputs.evidence
        ]
    author = SimpleNamespace(
        company_id=company,
        actor_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        fence=2,
        state="verifying",
    )
    pair = SimpleNamespace(author=author, author_child=MagicMock(), verifier_child=MagicMock())
    monkeypatch.setattr(input_reader, "resolve_strategy_pair_locked", AsyncMock(return_value=pair))
    monkeypatch.setattr(input_reader, "require_brain_scope", AsyncMock())
    monkeypatch.setattr(
        input_reader, "native_manifest", AsyncMock(return_value=(snapshot.inputs, "internal"))
    )
    monkeypatch.setattr(publication_protection, "validate_plan_profile", MagicMock())
    monkeypatch.setattr(
        publication_protection, "require_resources", AsyncMock(return_value=(source.grant,))
    )
    monkeypatch.setattr(
        publication_protection, "recipients", AsyncMock(return_value=(source.grant,))
    )

    async def clock(*_: object) -> datetime:
        return source.clock["now"]

    monkeypatch.setattr(input_reader, "db_now", clock)
    monkeypatch.setattr(publication_protection, "db_now", clock)
    from nexus.company.strategy import original_reader

    monkeypatch.setattr(original_reader, "db_now", clock)
    monkeypatch.setattr(original_reader, "require_brain_scope", AsyncMock())

    async def get(model: type[object], key: object) -> object:
        if model is BrainSource:
            return source.native
        if model is BrainResource:
            assert isinstance(key, tuple) and len(key) == 2
            return BrainResource(
                company_id=company, resource_id=key[1], kind="artifact", active=True
            )
        return rows.get((model, key))

    row_get = AsyncMock(side_effect=get)
    source.session.get = row_get

    async def metadata(statement: object) -> MagicMock:
        params = statement.compile().params  # type: ignore[attr-defined]
        row = rows.get((BrainArtifactRevision, (company, params["artifact_revision_id_1"])))
        result = MagicMock()
        assert row is None or isinstance(row, BrainArtifactRevision)
        result.one_or_none.return_value = (
            None
            if row is None
            else (
                row.artifact_id,
                row.artifact_revision_id,
                row.revision,
                row.sha256,
                row.byte_length,
            )
        )
        return result

    source.session.execute = AsyncMock(side_effect=metadata)
    source.session.scalar = AsyncMock(return_value=False)

    async def scalars(statement: object) -> MagicMock:
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        params = statement.compile().params  # type: ignore[attr-defined]
        key = params.get("artifact_revision_id_1", params.get("derivation_id_1"))
        result = MagicMock()
        result.all.return_value = edges[(entity.__tablename__, key)]
        return result

    source.session.scalars = AsyncMock(side_effect=scalars)
    source.clock["now"] = now + timedelta(seconds=4)
    return ReaderCase(source, reader, prepared, rows, edges, action, effect, row_get)
