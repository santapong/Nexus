"""Actual-shaped native row/edge checks with mocked SQL, not PostgreSQL qualification."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.strategy import publication_rows as module
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.publication_identity import prepare_strategy_publication
from nexus.tests.unit.strategy_producer_fixture import producer_case


def test_row_layout_retains_original_manifest_and_adds_bundle_only_to_brief() -> None:
    snapshot, policy = producer_case()
    target = ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=500))
    prepared = prepare_strategy_publication(snapshot, policy, UUID(int=501), target)
    rows = module.publication_layout(prepared)
    assert len(rows) == 2
    assert rows[0].reference == prepared.compiled.original_bundle.artifact
    assert rows[0].inputs == snapshot.inputs.artifacts
    assert rows[1].reference == prepared.brief
    assert rows[1].inputs == (*snapshot.inputs.artifacts, rows[0].reference)
    assert prepared.compiled.prepared.inputs == snapshot.inputs


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_text", "changed"),
        ("resource_id", UUID(int=999)),
        ("storage_symbol", "foreign"),
        ("data_classification", "public"),
        ("derivation_id", UUID(int=999)),
    ],
)
def test_exact_replay_cannot_replace_immutable_artifact_field(field: str, value: object) -> None:
    snapshot, policy = producer_case()
    prepared = prepare_strategy_publication(
        snapshot,
        policy,
        UUID(int=501),
        ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=500)),
    )
    layout = module.publication_layout(prepared)[0]
    row = BrainArtifactRevision(
        company_id=snapshot.company_id,
        artifact_id=layout.reference.artifact_id,
        artifact_revision_id=layout.reference.artifact_revision_id,
        revision=layout.reference.revision,
        raw_text=layout.raw.decode(),
        sha256=layout.reference.sha256,
        byte_length=len(layout.raw),
        resource_id=prepared.compiled.original_bundle.resource.resource_id,
        derivation_id=layout.derivation_id,
        storage_symbol="fixture",
        media_type="application/json",
        data_classification=prepared.compiled.prepared.data_classification,
    )
    module.require_artifact_row(row, layout, prepared, "fixture")
    setattr(row, field, value)
    with pytest.raises(ValueError):
        module.require_artifact_row(row, layout, prepared, "fixture")


async def test_write_both_graphs_uses_original_sources_and_evidence_without_effect_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This >50-line scenario binds both graph appends, policy, source/evidence and no-effect check.
    snapshot, policy = producer_case()
    prepared = prepare_strategy_publication(
        snapshot,
        policy,
        UUID(int=501),
        ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=500)),
    )
    scope = BrainReadScope(
        company_id=snapshot.company_id,
        workspace_id=UUID(int=3),
        principal_id=UUID(int=4),
        operation_id=UUID(int=502),
        trace_id=UUID(int=6),
    )
    rule = StrategyArtifactRule(
        company_id=snapshot.company_id,
        tool="company.cycle-artifact.write.v1",
        resource_symbol="strategy.output",
        target=prepared.compiled.original_bundle.resource,
        source_policy="generated.strategy.v1",
    )
    source_policy = SourcePolicy(
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
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.in_transaction.return_value = True
    monkeypatch.setattr(module, "validate_derivation", AsyncMock())
    save = AsyncMock()
    monkeypatch.setattr(module, "save_derivation", save)
    events = AsyncMock()
    monkeypatch.setattr(module, "append_event", events)
    await module.write_strategy_publication_locked(
        session,
        scope,
        prepared,
        rule,
        source_policy,
        source_policy.model_copy(update={"source_symbol": "generated.strategy.v1"}),
        "fixture",
        datetime.now(UTC),
    )
    assert save.await_count == events.await_count == 2
    for call in save.await_args_list:
        derivation = call.args[1]
        assert derivation.contributors == snapshot.inputs.contributors
        assert derivation.evidence == snapshot.inputs.evidence
    assert (
        len(
            [
                call
                for call in session.add.call_args_list
                if isinstance(call.args[0], BrainArtifactRevision)
            ]
        )
        == 2
    )
    assert all(
        call.args[0].__class__.__name__
        not in {"EffectIntent", "CostHold", "ExecutionAttempt", "BrainSourceHead"}
        for call in session.add.call_args_list
    )
